"""
Orchestration du fetch automatique des exports LightSpeed reçus par mail.

Pour chaque client ayant un tenant + une boîte mail configurés (page
Clients), et pour chaque mail non lu avec pièce jointe dans cette boîte :

1. identifie client + point de vente à partir de l'adresse destinataire
   (core.email_ingest.identifier_source) — jamais depuis le nom de fichier ;
2. adresse inconnue -> alerte interne + notification à l'adresse qui a reçu
   le mail (même non reconnue par la Table de correspondance : utile si un
   référentiel a été modifié par erreur, pour que quelqu'un côté client s'en
   rende compte sans dépendre de l'alerte interne), mail marqué lu (pas de
   réessai en boucle : l'alerte suffit, le mail original reste consultable) ;
3. adresse connue -> parse + convertit avec le référentiel du client
   identifié, exactement le même pipeline que l'import manuel (app.py) ;
4. archive la tentative dans l'historique du client, succès ou échec, avec
   le(s) destinataire(s) concerné(s) ;
5. répond : succès -> fichiers + récapitulatif ; échec (fichier illisible,
   mapping manquant...) -> le motif de l'échec, avec le fichier source
   d'origine en pièce jointe (pour comparer facilement l'erreur au fichier
   concerné, pas de CSV Pennylane vu qu'aucun n'a pu être généré) ; dans les
   deux cas à l'adresse « résultat » du point de vente si elle est
   configurée (Table de correspondance), sinon à l'adresse de réception
   d'origine — plus, en cas d'échec, une alerte interne avec le même détail ;
6. marque le mail source comme lu.

Ce module ne dépend d'aucun SDK Graph concret : `graph` n'importe quoi
d'objet exposant les méthodes utilisées ci-dessous (cf. core.graph_client.
GraphClient) — ce qui permet de tester toute cette orchestration avec un
faux client, sans réseau ni tenant Azure réel.
"""
from __future__ import annotations

import email.utils
import html
import logging
import os
import re

from core.app_config import get_alerte_interne, get_azure_credentials_globaux, get_url_app
from core.client_store import get_prefixe_mail, list_clients
from core.converter import convert
from core.consolidation_sas import (
    DELAI_ALERTE_HEURES,
    charger_paire,
    cle_appariement,
    deposer,
    est_complet,
    marquer_echec,
    marquer_signale,
    paires_en_echec,
    orphelins_a_signaler,
    purger_expires,
    rapport_manquant,
    retirer,
)
from core.email_ingest import EmailIngestError, SourceIdentifiee, date_aaaammjj, identifier_source
from core.history_store import record_consolidation, record_conversion
from core.lightspeed_parser import LightspeedParseError, parse_lightspeed_export
from core.lightspeed_synthese import SITES, SyntheseError, classer_fichiers, construire_synthese
from core.mapping_store import TRAITEMENT_CONSOLIDATION, find_pdv, load_mappings
from core.pennylane_export import build_pennylane_csv
from core.timezone import now_local

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".xls", ".xlsx", ".csv")


def _extension_supportee(filename: str) -> bool:
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def _adresse_alerte_interne() -> str | None:
    """Réglage de l'application, à défaut variable d'environnement
    (cf. core.app_config.get_alerte_interne)."""
    return get_alerte_interne() or None


def _adresses_destinataires(message: dict) -> list[str]:
    """Adresses destinataires candidates pour l'identification, dans l'ordre
    de préférence. Priorité à l'en-tête RFC5322 `To:` brut
    (`internetMessageHeaders`, tel qu'écrit par l'expéditeur, jamais réécrit
    en transit) plutôt qu'à `toRecipients` : quand la boîte interrogée est
    jointe via un alias (plusieurs adresses dédiées sur une même boîte
    partagée, une par point de vente — cf. docs/configuration_m365_client.md),
    Exchange résout `toRecipients` contre l'annuaire et le normalise vers
    l'adresse **principale** de la boîte, perdant l'alias réellement utilisé.
    Repli sur `toRecipients` si l'en-tête est absent (permission insuffisante,
    ou mail sans en-tête To exploitable)."""
    for header in message.get("internetMessageHeaders") or []:
        if header.get("name", "").lower() == "to":
            adresses = [a for _, a in email.utils.getaddresses([header.get("value", "")]) if a]
            if adresses:
                return adresses
    return [r["emailAddress"]["address"] for r in message.get("toRecipients", [])]


def traiter_client(graph, client: dict) -> int:
    """Traite tous les mails en attente de la boîte configurée pour ce
    client. Ne fait rien si tenant/boîte ne sont pas renseignés (fetch
    automatique non activé pour ce client). Retourne le nombre de mails
    effectivement récupérés (pièce jointe exploitable trouvée, marqués lus) -
    utile pour restituer un compte-rendu, ex. bouton « Relever les mails
    maintenant » (page Convertisseur)."""
    tenant_id = client.get("email_tenant_id")
    mailbox = client.get("email_mailbox")
    if not tenant_id or not mailbox:
        return 0

    prefixe_mail = get_prefixe_mail(client)
    nb_recuperes = 0
    for message in graph.list_unread_with_attachments(mailbox):
        if traiter_message(graph, mailbox, message, prefixe_mail):
            nb_recuperes += 1
    # Reprise AVANT le signalement : une paire en échec peut aboutir maintenant
    # (référentiel corrigé entre deux cycles), inutile de la compter parmi les
    # incidents si elle vient de repartir.
    reprendre_paires_en_echec(graph, mailbox, client["id"], prefixe_mail)
    # Et après le traitement des messages, pas avant : un rapport attendu
    # depuis 4 h peut très bien être complété par le cycle en cours.
    signaler_orphelins(graph, mailbox, client["id"])
    return nb_recuperes


def traiter_message(graph, mailbox: str, message: dict, prefixe_mail: str = "LS2PL") -> bool:
    """Retourne True si le mail a été effectivement récupéré (pièce jointe
    exploitable trouvée, marqué lu), False sinon (ex. mail de correspondance
    normale sur cette boîte, sans export LightSpeed reconnu — laissé non lu)."""
    adresses_candidates = _adresses_destinataires(message)
    fichiers = [
        f for f in graph.list_file_attachments(mailbox, message["id"])
        if _extension_supportee(f["name"])
    ]

    # Aucune pièce jointe exploitable (ex : mail de correspondance normale sur
    # cette boîte, avec juste une image de signature) : on laisse le mail non
    # lu plutôt que d'alerter à tort — seule une pièce jointe reconnue comme
    # export LightSpeed déclenche un traitement ou une alerte.
    if not fichiers:
        return False

    for fichier in fichiers:
        _traiter_piece_jointe(graph, mailbox, adresses_candidates, fichier["name"], fichier["content"], prefixe_mail)

    graph.mark_as_read(mailbox, message["id"])
    return True


def _traiter_piece_jointe(
    graph, mailbox: str, adresses_candidates: list[str], filename: str, raw: bytes, prefixe_mail: str = "LS2PL",
) -> None:
    # Plusieurs adresses candidates (cf. _adresses_destinataires) : on essaie
    # chacune jusqu'à en trouver une rattachée à un point de vente — utile
    # notamment en repli (toRecipients) quand plusieurs destinataires
    # figurent sur le mail. Aucune de reconnue -> alerte avec le détail de la
    # dernière tentative.
    source = None
    adresse_cible = None
    derniere_erreur: EmailIngestError | None = None
    if not adresses_candidates:
        derniere_erreur = EmailIngestError(f"« {filename} » : mail sans destinataire exploitable.")
    else:
        for adresse in adresses_candidates:
            try:
                source = identifier_source(adresse, filename)
                adresse_cible = adresse
                break
            except EmailIngestError as exc:
                derniere_erreur = exc

    if source is None:
        detail = str(derniere_erreur)
        _alerter(graph, mailbox, sujet=f"Export LightSpeed non identifié — {filename}", detail=detail)
        # Notifie aussi l'adresse (ou les adresses) ayant reçu ce mail, même non
        # reconnue(s) par la Table de correspondance : sans client/point de vente
        # identifié, impossible de résoudre une adresse_resultat, donc on répond
        # directement à l'adresse candidate elle-même (alias de la boîte
        # partagée) — utile en particulier si une entrée du référentiel a été
        # modifiée ou supprimée par erreur.
        _notifier_echec_client(
            graph, mailbox, adresses_candidates,
            sujet="Échec de traitement automatique de votre export LightSpeed",
            filename=filename, detail=detail, raw=raw, prefixe_mail=prefixe_mail,
        )
        return

    mappings = load_mappings(source.client_id)
    pdv = find_pdv(mappings, source.code_pdv)
    # adresse_resultat (Table de correspondance > Points de vente) permet de renvoyer
    # ailleurs qu'à l'adresse de réception (ex. la comptable plutôt que la boîte
    # partagée elle-même) ; vide par défaut -> repli sur l'adresse d'origine.
    # Plusieurs destinataires possibles, séparés par une virgule ou un point-virgule.
    # Sert à la fois pour le résultat (succès) et la notification d'échec.
    adresses_notification = _adresses_resultat(pdv, repli=adresse_cible)
    periode = f"{source.date_debut or '?'} → {source.date_fin or '?'}"

    # C'est l'adresse destinataire qui a décidé du traitement, pas le nom du
    # fichier (cf. core.email_ingest) : un point de vente a une adresse pour
    # ses exports comptables et une autre pour ses rapports d'exploitation.
    if source.traitement == TRAITEMENT_CONSOLIDATION:
        _traiter_rapport_consolidation(
            graph, mailbox, source, pdv, adresses_notification, filename, raw, periode, prefixe_mail
        )
        return

    try:
        export = parse_lightspeed_export(raw, filename)
    except LightspeedParseError as exc:
        detail = str(exc)
        _alerter(
            graph, mailbox,
            sujet=f"Export LightSpeed illisible — {source.client_id}/{source.code_pdv} — {filename}",
            detail=detail,
        )
        _notifier_echec_client(
            graph, mailbox, adresses_notification,
            sujet=f"Échec de traitement de votre export LightSpeed — {source.code_pdv}",
            filename=filename, detail=detail, raw=raw, point_de_vente=source.code_pdv, periode=periode,
            prefixe_mail=prefixe_mail,
        )
        return

    # Si la période n'a pas pu être déduite du nom de fichier (source.avertissement
    # renseigné), on retombe sur la date du jour de traitement pour la pièce comptable ;
    # l'avertissement est repris dans l'alerte en cas d'échec plus bas, à vérifier manuellement.
    date_piece = source.date_debut or now_local().strftime("%d/%m/%y")
    numero_piece = f"LS-{date_piece.replace('/', '')}-{source.code_pdv}"

    res = convert(
        export,
        mappings,
        point_de_vente=source.code_pdv,
        date_piece=date_piece,
        numero_piece=numero_piece,
        # Pas de code journal imposé ici : la conversion applique la cascade
        # (journal du point de vente, à défaut celui des paramètres généraux) -
        # sur le chemin automatique, personne n'est là pour le saisir.
    )

    horodatage = now_local().strftime("%Y-%m-%d %H:%M:%S")
    csv_bytes = build_pennylane_csv([res])
    record_conversion(source.client_id, res, raw, csv_bytes, horodatage, destinataires_email=adresses_notification)

    if res.sans_erreur:
        _envoyer_resultat(graph, mailbox, adresses_notification, source, res, raw, csv_bytes, date_piece, prefixe_mail)
    else:
        detail = "\n".join(res.erreurs)
        if source.avertissement:
            detail = f"{source.avertissement}\n{detail}"
        _alerter(
            graph, mailbox,
            sujet=f"Échec de conversion LightSpeed → Pennylane — {source.client_id}/{source.code_pdv} — {filename}",
            detail=detail,
        )
        _notifier_echec_client(
            graph, mailbox, adresses_notification,
            sujet=f"Échec de conversion de votre export LightSpeed — {source.code_pdv}",
            filename=filename, detail=detail, raw=raw, point_de_vente=source.code_pdv, periode=periode,
            prefixe_mail=prefixe_mail,
        )


# --- Consolidation : appariement de deux rapports arrivés séparément --------


def _traiter_rapport_consolidation(
    graph, mailbox: str, source, pdv: dict | None, adresses_notification: list[str],
    filename: str, raw: bytes, periode: str, prefixe_mail: str,
) -> None:
    """Range un rapport dans le sas d'attente, puis consolide dès que son
    binôme est là (cf. core.consolidation_sas). Un rapport seul ne produit
    rien et n'est pas une anomalie : c'est le fonctionnement normal, les deux
    rapports arrivant dans deux messages distincts."""
    tickets, transactions, _ = classer_fichiers([filename])
    type_rapport = "tickets" if tickets else ("transactions" if transactions else None)

    if type_rapport is None:
        detail = (
            f"« {filename} » : impossible de dire s'il s'agit du rapport Tickets ou du rapport "
            "Transactions. Le nom d'un export Lightspeed doit contenir « _tickets_ » ou "
            "« _transactions_ » pour pouvoir être apparié automatiquement."
        )
        _alerter(graph, mailbox, sujet=f"Rapport de consolidation non identifié — {filename}", detail=detail)
        _notifier_echec_client(
            graph, mailbox, adresses_notification, sujet="Échec de traitement de votre rapport Lightspeed",
            filename=filename, detail=detail, raw=raw, point_de_vente=source.code_pdv,
            periode=periode, prefixe_mail=prefixe_mail,
        )
        return

    if not source.date_debut or not source.date_fin:
        detail = (
            f"« {filename} » : période introuvable dans le nom du fichier (deux dates AAAAMMJJ "
            "attendues en fin de nom). Sans elle, impossible de savoir à quel autre rapport "
            "l'apparier."
        )
        _alerter(graph, mailbox, sujet=f"Rapport de consolidation non appariable — {filename}", detail=detail)
        _notifier_echec_client(
            graph, mailbox, adresses_notification, sujet="Échec de traitement de votre rapport Lightspeed",
            filename=filename, detail=detail, raw=raw, point_de_vente=source.code_pdv,
            periode=periode, prefixe_mail=prefixe_mail,
        )
        return

    horodatage = now_local().strftime("%Y-%m-%d %H:%M:%S")
    etat = deposer(
        source.client_id, source.code_pdv, source.date_debut, source.date_fin,
        type_rapport, filename, raw, horodatage, adresses_notification,
    )

    if not est_complet(etat):
        log.info(
            "Consolidation %s/%s %s : rapport %s reçu, en attente de %s.",
            source.client_id, source.code_pdv, periode, type_rapport, rapport_manquant(etat),
        )
        return

    _consolider_paire(graph, mailbox, source, pdv, etat, periode, prefixe_mail)


def _consolider_paire(graph, mailbox: str, source, pdv: dict | None, etat: dict,
                      periode: str, prefixe_mail: str) -> bool:
    """Paire complète : consolide, archive, envoie. Renvoie True en cas de
    succès (la paire est alors retirée du sas), False sinon.

    En cas d'échec la paire RESTE dans le sas — les fichiers y sont la seule
    copie disponible côté application. Elle est retentée à chaque cycle, la
    cause étant presque toujours à corriger dans le référentiel (cf.
    reprendre_paires_en_echec) ; le motif est mémorisé pour ne notifier qu'une
    fois par cause.

    `graph` peut être None : la consolidation est alors calculée et archivée
    sans aucun envoi de mail. C'est ce que fait la relance manuelle depuis la
    page Consolidation, où l'utilisateur voit le résultat à l'écran et où le
    client n'a pas forcément de boîte configurée."""
    cle = etat["cle"]
    # Destinataires des deux messages confondus : ils sont normalement
    # identiques, mais si l'adresse résultat a changé entre les deux, mieux
    # vaut informer les deux que d'en oublier un.
    adresses = list(dict.fromkeys(
        a for r in etat["rapports"].values() for a in (r.get("adresses_notification") or [])
    ))
    noms = ", ".join(r["nom_fichier"] for r in etat["rapports"].values())

    def echouer(detail: str, sujet: str) -> bool:
        nouveau = marquer_echec(source.client_id, cle, detail, now_local().strftime("%Y-%m-%d %H:%M:%S"))
        # Même motif qu'au passage précédent : déjà signalé, on ne répète pas.
        if graph is not None and nouveau:
            _alerter(graph, mailbox, sujet=f"{sujet} — {source.code_pdv} {periode}", detail=detail)
            _notifier_echec_client(
                graph, mailbox, adresses, sujet="Échec de consolidation de vos rapports Lightspeed",
                filename=noms, detail=detail, point_de_vente=source.code_pdv, periode=periode,
                prefixe_mail=prefixe_mail,
            )
        return False

    site = ((pdv or {}).get("site_consolidation") or "").strip().upper()
    if site not in SITES:
        detail = (
            f"Point de vente « {source.code_pdv} » : le site de consolidation n'est pas renseigné "
            f"(attendu : {', '.join(SITES)}). Il détermine les périodes de service, la consolidation "
            "ne peut pas être calculée sans lui — à compléter dans la Table de correspondance, "
            "onglet Points de vente, puis relancer la consolidation manuellement."
        )
        return echouer(detail, "Consolidation impossible")

    paire = charger_paire(source.client_id, cle)
    if paire is None:
        return echouer(
            f"Les fichiers du sas d'attente sont introuvables pour la clé {cle}.",
            "Consolidation impossible",
        )

    try:
        res = construire_synthese(
            paire[0], paire[1], site, periode=(etat.get("date_debut"), etat.get("date_fin"))
        )
    except SyntheseError as exc:
        return echouer(f"{exc}", "Échec de consolidation")

    sources = list(paire[0]) + list(paire[1])
    record_consolidation(source.client_id, res, sources, now_local().strftime("%Y-%m-%d %H:%M:%S"))
    if graph is not None:
        _envoyer_resultat_consolidation(graph, mailbox, adresses, source, res, sources, prefixe_mail)
    retirer(source.client_id, cle)
    return True


def _envoyer_resultat_consolidation(
    graph, mailbox, adresses: list[str], source, res, sources: list, prefixe_mail: str,
) -> None:
    sans_vente = (
        "<p><b>Aucune vente sur cette période</b> — le rapport Tickets est vide : journée sans "
        "activité (fermeture, jour férié...). Les totaux sont à zéro, ce n'est pas une erreur de "
        "traitement. Si la journée aurait dû être ouverte, c'est l'export LightSpeed qu'il faut "
        "vérifier.</p>"
    ) if res.sans_vente else ""
    alerte = "" if res.sans_anomalie_bloquante else (
        f"<p>❌ Écart de {res.ecart_controle:+.2f} € entre le total des transactions et celui des "
        "tickets : les deux rapports ne couvrent probablement pas exactement la même période. "
        "Les totaux ci-dessus ne sont pas fiables en l'état.</p>"
    )
    a_verifier = res.anomalies_a_verifier
    corps = (
        f"<p>Consolidation automatique effectuée pour <b>{source.client_id} / {source.code_pdv}</b> "
        f"({res.site} — {res.periode_libelle}).</p>"
        f"<ul>"
        f"<li>CA TTC : {res.ca_ttc:,.2f} €</li>"
        f"<li>CA HT : {res.ca_ht:,.2f} €</li>"
        f"<li>Couverts : {res.couverts}</li>"
        f"<li>{res.nb_tickets} tickets, {res.nb_lignes} lignes de transaction</li>"
        f"</ul>"
        + sans_vente
        + alerte
        + (f"<p>⚠️ {len(a_verifier)} point(s) à vérifier — voir l'onglet ANOMALIES du classeur.</p>" if a_verifier else "")
        + _pied_de_page_lien_app()
    )
    jour = res.jours[0].strftime("%Y%m%d") if res.jours else "sansdate"
    graph.send_mail(
        mailbox,
        subject=f"[{prefixe_mail}] Consolidation - {source.client_id.upper()}/{source.code_pdv} - "
                f"{res.periode_libelle}" + (" - sans vente" if res.sans_vente else ""),
        body_html=corps,
        to_addresses=adresses,
        attachments=[(nom, contenu) for nom, contenu in sources]
        + [(f"synthese_{res.site.lower()}_{jour}.xlsx", res.classeur)],
    )


def reprendre_paires_en_echec(graph, mailbox: str, client_id: str, prefixe_mail: str = "LS2PL") -> int:
    """Retente les paires complètes restées dans le sas, et renvoie le nombre
    de consolidations enfin abouties.

    Sans ça, une paire en échec est une impasse : le traitement n'est
    déclenché que par l'ARRIVÉE d'un rapport, or les deux sont déjà là. Elle
    resterait donc indéfiniment, même une fois la cause corrigée — c'est
    exactement ce qui s'est produit en production, douze jours durant.

    Retenter coûte une lecture de fichiers locaux ; la notification, elle, est
    dédoublonnée sur le motif (cf. consolidation_sas.marquer_echec), donc
    aucune répétition tant que la cause ne change pas.

    `graph` peut être None : les paires sont alors consolidées et archivées
    sans envoi de mail (relance manuelle depuis la page Consolidation)."""
    mappings = load_mappings(client_id)
    reussies = 0
    for etat in paires_en_echec(client_id):
        code_pdv = etat.get("code_pdv", "")
        source = SourceIdentifiee(
            client_id=client_id,
            code_pdv=code_pdv,
            date_debut=etat.get("date_debut"),
            date_fin=etat.get("date_fin"),
            traitement=TRAITEMENT_CONSOLIDATION,
        )
        periode = f"{etat.get('date_debut') or '?'} → {etat.get('date_fin') or '?'}"
        if _consolider_paire(graph, mailbox, source, find_pdv(mappings, code_pdv), etat, periode, prefixe_mail):
            reussies += 1
            log.info("Consolidation reprise avec succès : %s/%s %s", client_id, code_pdv, periode)
    return reussies


def signaler_orphelins(graph, mailbox: str, client_id: str) -> int:
    """Signale les rapports restés seuls au-delà de DELAI_ALERTE_HEURES, et
    abandonne ceux devenus trop anciens. Appelé à chaque cycle : sans ça, un
    export qui ne part plus côté Lightspeed passerait inaperçu, la
    consolidation se contentant de ne jamais se déclencher."""
    maintenant = now_local().replace(tzinfo=None)
    nb = 0
    for etat in orphelins_a_signaler(client_id, maintenant):
        manquant = rapport_manquant(etat)
        recu = [t for t in etat["rapports"]]
        _alerter(
            graph, mailbox,
            sujet=f"Rapport de consolidation manquant — {etat['code_pdv']} "
                  f"{etat.get('date_debut') or '?'} → {etat.get('date_fin') or '?'}",
            detail=(
                f"Le rapport « {manquant} » n'est toujours pas arrivé plus de {DELAI_ALERTE_HEURES} h "
                f"après « {', '.join(recu)} » ({etat['client_id']} / {etat['code_pdv']}). "
                "La consolidation reste en attente : vérifier l'export automatique côté Lightspeed. "
                "Le rapport déjà reçu est conservé, un envoi tardif complétera la paire."
            ),
        )
        marquer_signale(client_id, etat["cle"])
        nb += 1
    purger_expires(client_id, maintenant)
    return nb


def decouper_adresses(brut: str | None) -> list[str]:
    """Découpe une saisie libre en adresses individuelles, séparées par une
    virgule ou un point-virgule (ex. "compta@..., direction@...").

    Microsoft Graph attend UNE adresse par destinataire : lui transmettre la
    chaîne entière le fait chercher une boîte dont le nom contient la virgule,
    et il rejette l'envoi complet (ErrorInvalidRecipients). Tout champ d'adresse
    saisi à la main doit donc passer par ici."""
    return [a.strip() for a in re.split(r"[,;]", brut or "") if a.strip()]


def _adresses_resultat(pdv: dict | None, repli: str) -> list[str]:
    """Destinataire(s) du résultat pour ce point de vente : le champ
    adresse_resultat (Table de correspondance) accepte plusieurs adresses.
    Vide/absent -> repli sur `repli` (l'adresse de réception d'origine)."""
    adresses = decouper_adresses((pdv or {}).get("adresse_resultat"))
    return adresses or [repli]


def _pied_de_page_lien_app() -> str:
    """Petit pied de page HTML pointant vers l'application (URL renseignée
    page Réglages > Informations), ajouté aux mails de conversion réussie
    pour s'y rendre en un clic (ex. consulter l'historique). Vide si l'URL
    n'est pas configurée — pas de mention à la place, pour ne pas alourdir
    le mail d'un texte sans lien cliquable."""
    url_app = get_url_app()
    if not url_app:
        return ""
    return (
        f'<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">'
        f'<p style="color:#666;font-size:0.9em;">Application LS2PL : <a href="{url_app}">{url_app}</a></p>'
    )


def _envoyer_resultat(
    graph, mailbox, adresses_resultat, source, res, raw: bytes, csv_bytes: bytes, date_piece: str,
    prefixe_mail: str = "LS2PL",
) -> None:
    corps = (
        f"<p>Conversion automatique effectuée pour <b>{source.client_id} / {source.code_pdv}</b> "
        f"({source.date_debut or '?'} → {source.date_fin or '?'}).</p>"
        f"<ul>"
        f"<li>CA HT : {res.ca_ht_source:,.2f} €</li>"
        f"<li>TVA collectée : {res.tva_source:,.2f} €</li>"
        f"<li>Total TTC : {res.ttc_source:,.2f} €</li>"
        f"</ul>"
        + (f"<p>⚠️ {len(res.avertissements)} avertissement(s) — voir l'historique de l'application.</p>" if res.avertissements else "")
        + _pied_de_page_lien_app()
    )
    graph.send_mail(
        mailbox,
        subject=f"[{prefixe_mail}] LS2PL - {source.client_id.upper()}/{source.code_pdv} - {source.date_debut or ''}",
        body_html=corps,
        # adresses_resultat = adresse_resultat du point de vente (Table de correspondance,
        # une ou plusieurs séparées par virgule/point-virgule) si renseignée, sinon
        # l'adresse de réception d'origine (fallback résolu par l'appelant, jamais
        # l'alerte interne) — cf. docstring du module.
        to_addresses=adresses_resultat,
        attachments=[
            (res.source_filename, raw),
            (f"import_pl_{source.client_id}_{source.code_pdv}_{date_aaaammjj(date_piece)}.csv", csv_bytes),
        ],
    )


def _corps_notification_echec(
    filename: str, detail: str, point_de_vente: str | None = None, periode: str | None = None
) -> str:
    """Corps HTML du mail de notification d'échec envoyé côté client : le
    contexte (point de vente/période si connus, nom du fichier), le motif
    exact de l'échec, puis une invitation à vérifier/corriger et relancer une
    conversion manuelle, avec un lien direct vers l'historique si l'URL de
    l'application est renseignée (page Réglages > Informations)."""
    contexte = f"point de vente {point_de_vente}" if point_de_vente else "un point de vente non identifié"
    if periode:
        contexte += f", période {periode}"

    detail_html = html.escape(detail).replace("\n", "<br>")

    url_app = get_url_app()
    lien = f"{url_app}/historique" if url_app else None
    invitation = (
        f'rendez-vous sur <a href="{lien}">{lien}</a>' if lien
        else "rendez-vous sur la page « Historique » de l'application"
    )

    return (
        f"<p>Signalement d'un échec avec l'export du <b>{contexte}</b>, "
        f"dont le nom de fichier est <code>{html.escape(filename)}</code>.</p>"
        f"<p><b>Erreur :</b><br>{detail_html}</p>"
        f"<p>Pour vérifier l'historique et effectuer les corrections nécessaires (référentiel, "
        f"table de correspondance...) avant de relancer une conversion manuelle avec ce même "
        f"fichier, {invitation} (sélectionnez le client concerné dans le menu, page Convertisseur "
        f"pour réimporter).</p>"
    )


def _notifier_echec_client(
    graph, mailbox, destinataires: list[str], sujet: str, filename: str, detail: str,
    raw: bytes | None = None, point_de_vente: str | None = None, periode: str | None = None,
    prefixe_mail: str = "LS2PL",
) -> None:
    """Notifie, en plus de l'alerte interne (_alerter), le(s) destinataire(s)
    côté client concerné(s) par un échec — y compris quand l'adresse
    destinataire elle-même n'est pas reconnue (ex. une entrée modifiée par
    erreur dans la Table de correspondance) : sans ça, seule Polyskills le
    saurait, à condition d'avoir configuré LSPENNYLANE_ALERTE_INTERNE, sans
    jamais remonter jusqu'à qui pourrait corriger le référentiel. Le fichier
    source d'origine est joint (raw, si connu) pour que le destinataire
    puisse comparer directement le motif de l'échec au fichier concerné,
    sans avoir à le retrouver dans sa messagerie — jamais de CSV Pennylane
    ici (contrairement à _envoyer_resultat), vu qu'aucun n'a pu être
    généré."""
    destinataires = [a for a in dict.fromkeys(destinataires) if a]  # dédoublonne, préserve l'ordre
    if not destinataires:
        return
    graph.send_mail(
        mailbox,
        subject=f"[{prefixe_mail}] {sujet}",
        body_html=_corps_notification_echec(filename, detail, point_de_vente, periode),
        to_addresses=destinataires,
        attachments=[(filename, raw)] if raw is not None else None,
    )


def _alerter(graph, mailbox: str, sujet: str, detail: str) -> None:
    # Découpé comme adresse_resultat : ce champ est saisi à la main (Réglages >
    # Gestion Email) et y mettre deux adresses séparées par une virgule est
    # naturel. Transmise en bloc, la chaîne entière serait prise par Graph pour
    # une seule adresse, et TOUTE l'alerte serait rejetée - donc perdue, alors
    # que c'est précisément le canal qui signale les incidents.
    destinataires = decouper_adresses(_adresse_alerte_interne())
    if not destinataires:
        # Aucune adresse d'alerte configurée : rien à envoyer, mais un log
        # explicite évite un échec complètement silencieux (ni mail, ni trace).
        log.warning("[Alerte fetch LightSpeed] %s — %s", sujet, detail)
        return
    graph.send_mail(
        mailbox,
        subject=f"[Alerte fetch LightSpeed] {sujet}",
        body_html=f"<p>{detail}</p>",
        to_addresses=destinataires,
    )


def _identifiants_azure(client: dict) -> tuple[str, str] | None:
    """ID d'application + secret client Azure AD à utiliser pour ce client :
    priorité aux champs propres au client (azure_client_id/azure_client_secret,
    Réglages > Gestion Email — cf. core.client_store.set_azure_credentials),
    sinon repli sur les identifiants globaux de l'application (Réglages >
    Gestion Email, eux-mêmes repliant sur les variables d'environnement
    LSPENNYLANE_AZURE_CLIENT_ID/_SECRET — cf. core.app_config). Ces
    identifiants globaux ne conviennent que tant qu'un seul tenant est
    concerné sur ce serveur, puisqu'ils sont partagés par tous les clients.
    None si aucune des deux sources n'est disponible."""
    globaux_id, globaux_secret = get_azure_credentials_globaux()
    azure_client_id = client.get("azure_client_id") or globaux_id
    azure_client_secret = client.get("azure_client_secret") or globaux_secret
    if not azure_client_id or not azure_client_secret:
        return None
    return azure_client_id, azure_client_secret


def executer_un_cycle() -> None:
    """Un passage sur tous les clients configurés. Appelé en boucle par le
    script d'entrée `email_poller.py` (intervalle réglable). Les clients sans
    identifiants Azure disponibles (ni propres, ni en repli via les
    variables d'environnement) sont ignorés silencieusement plutôt que de
    faire échouer tout le cycle pour les autres clients."""
    from core.graph_client import GraphClient

    for client in list_clients():
        tenant_id = client.get("email_tenant_id")
        if not tenant_id:
            continue
        identifiants = _identifiants_azure(client)
        if identifiants is None:
            log.warning(
                "Fetch mail ignoré pour le client %s : aucun identifiant Azure disponible "
                "(ni propre au client, ni en variable d'environnement).",
                client.get("id"),
            )
            continue
        azure_client_id, azure_client_secret = identifiants
        graph = GraphClient(tenant_id=tenant_id, client_id=azure_client_id, client_secret=azure_client_secret)
        traiter_client(graph, client)
