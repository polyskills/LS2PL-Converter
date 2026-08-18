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
   mapping manquant...) -> le motif de l'échec, sans fichier joint ; dans les
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

from core.app_config import get_url_app
from core.client_store import list_clients
from core.converter import convert
from core.email_ingest import EmailIngestError, identifier_source
from core.history_store import record_conversion
from core.lightspeed_parser import LightspeedParseError, parse_lightspeed_export
from core.mapping_store import find_pdv, load_mappings
from core.pennylane_export import build_pennylane_csv
from core.timezone import now_local

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".xls", ".xlsx", ".csv")


def _extension_supportee(filename: str) -> bool:
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def _adresse_alerte_interne() -> str | None:
    return os.environ.get("LSPENNYLANE_ALERTE_INTERNE") or None


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


def traiter_client(graph, client: dict) -> None:
    """Traite tous les mails en attente de la boîte configurée pour ce
    client. Ne fait rien si tenant/boîte ne sont pas renseignés (fetch
    automatique non activé pour ce client)."""
    tenant_id = client.get("email_tenant_id")
    mailbox = client.get("email_mailbox")
    if not tenant_id or not mailbox:
        return

    for message in graph.list_unread_with_attachments(mailbox):
        traiter_message(graph, mailbox, message)


def traiter_message(graph, mailbox: str, message: dict) -> None:
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
        return

    for fichier in fichiers:
        _traiter_piece_jointe(graph, mailbox, adresses_candidates, fichier["name"], fichier["content"])

    graph.mark_as_read(mailbox, message["id"])


def _traiter_piece_jointe(graph, mailbox: str, adresses_candidates: list[str], filename: str, raw: bytes) -> None:
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
            filename=filename, detail=detail,
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
            filename=filename, detail=detail, point_de_vente=source.code_pdv, periode=periode,
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
        code_journal=mappings["parametres"].get("code_journal", "VT"),
    )

    horodatage = now_local().strftime("%Y-%m-%d %H:%M:%S")
    csv_bytes = build_pennylane_csv([res])
    record_conversion(source.client_id, res, raw, csv_bytes, horodatage, destinataires_email=adresses_notification)

    if res.sans_erreur:
        _envoyer_resultat(graph, mailbox, adresses_notification, source, res, raw, csv_bytes)
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
            filename=filename, detail=detail, point_de_vente=source.code_pdv, periode=periode,
        )


def _adresses_resultat(pdv: dict | None, repli: str) -> list[str]:
    """Destinataire(s) du résultat pour ce point de vente : le champ
    adresse_resultat (Table de correspondance) accepte plusieurs adresses
    séparées par une virgule ou un point-virgule (ex. "compta@..., direction@...").
    Vide/absent -> repli sur `repli` (l'adresse de réception d'origine)."""
    brut = ((pdv or {}).get("adresse_resultat") or "").strip()
    if not brut:
        return [repli]
    adresses = [a.strip() for a in re.split(r"[,;]", brut) if a.strip()]
    return adresses or [repli]


def _envoyer_resultat(graph, mailbox, adresses_resultat, source, res, raw: bytes, csv_bytes: bytes) -> None:
    corps = (
        f"<p>Conversion automatique effectuée pour <b>{source.client_id} / {source.code_pdv}</b> "
        f"({source.date_debut or '?'} → {source.date_fin or '?'}).</p>"
        f"<ul>"
        f"<li>CA HT : {res.ca_ht_source:,.2f} €</li>"
        f"<li>TVA collectée : {res.tva_source:,.2f} €</li>"
        f"<li>Total TTC : {res.ttc_source:,.2f} €</li>"
        f"</ul>"
        + (f"<p>⚠️ {len(res.avertissements)} avertissement(s) — voir l'historique de l'application.</p>" if res.avertissements else "")
    )
    graph.send_mail(
        mailbox,
        subject=f"Conversion LightSpeed → Pennylane — {source.client_id}/{source.code_pdv} — {source.date_debut or ''}",
        body_html=corps,
        # adresses_resultat = adresse_resultat du point de vente (Table de correspondance,
        # une ou plusieurs séparées par virgule/point-virgule) si renseignée, sinon
        # l'adresse de réception d'origine (fallback résolu par l'appelant, jamais
        # l'alerte interne) — cf. docstring du module.
        to_addresses=adresses_resultat,
        attachments=[(res.source_filename, raw), (f"import_pennylane_{res.point_de_vente}.csv", csv_bytes)],
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
    point_de_vente: str | None = None, periode: str | None = None,
) -> None:
    """Notifie, en plus de l'alerte interne (_alerter), le(s) destinataire(s)
    côté client concerné(s) par un échec — y compris quand l'adresse
    destinataire elle-même n'est pas reconnue (ex. une entrée modifiée par
    erreur dans la Table de correspondance) : sans ça, seule Polyskills le
    saurait, à condition d'avoir configuré LSPENNYLANE_ALERTE_INTERNE, sans
    jamais remonter jusqu'à qui pourrait corriger le référentiel. Aucun
    fichier joint ici (contrairement à _envoyer_resultat) : uniquement le
    motif de l'échec, en clair, et une invitation à corriger puis relancer
    manuellement (cf. _corps_notification_echec)."""
    destinataires = [a for a in dict.fromkeys(destinataires) if a]  # dédoublonne, préserve l'ordre
    if not destinataires:
        return
    graph.send_mail(
        mailbox,
        subject=f"[LS2PL] {sujet}",
        body_html=_corps_notification_echec(filename, detail, point_de_vente, periode),
        to_addresses=destinataires,
    )


def _alerter(graph, mailbox: str, sujet: str, detail: str) -> None:
    destinataire = _adresse_alerte_interne()
    if not destinataire:
        # Aucune adresse d'alerte configurée (LSPENNYLANE_ALERTE_INTERNE absente) :
        # rien à envoyer, mais un log explicite évite un échec complètement
        # silencieux (ni mail, ni trace) en test local sans cette variable.
        log.warning("[Alerte fetch LightSpeed] %s — %s", sujet, detail)
        return
    graph.send_mail(
        mailbox,
        subject=f"[Alerte fetch LightSpeed] {sujet}",
        body_html=f"<p>{detail}</p>",
        to_addresses=[destinataire],
    )


def executer_un_cycle() -> None:
    """Un passage sur tous les clients configurés. Appelé en boucle par le
    script d'entrée `email_poller.py` (intervalle réglable)."""
    from core.graph_client import GraphClient

    client_id = os.environ["LSPENNYLANE_AZURE_CLIENT_ID"]
    client_secret = os.environ["LSPENNYLANE_AZURE_CLIENT_SECRET"]

    for client in list_clients():
        tenant_id = client.get("email_tenant_id")
        if not tenant_id:
            continue
        graph = GraphClient(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
        traiter_client(graph, client)
