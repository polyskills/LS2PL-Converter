"""
Orchestration du fetch automatique des exports LightSpeed reçus par mail.

Pour chaque client ayant un tenant + une boîte mail configurés (page
Clients), et pour chaque mail non lu avec pièce jointe dans cette boîte :

1. identifie client + point de vente à partir de l'adresse destinataire
   (core.email_ingest.identifier_source) — jamais depuis le nom de fichier ;
2. adresse inconnue -> alerte interne, mail marqué lu (pas de réessai en
   boucle : l'alerte suffit, le mail original reste consultable) ;
3. adresse connue -> parse + convertit avec le référentiel du client
   identifié, exactement le même pipeline que l'import manuel (app.py) ;
4. archive la tentative dans l'historique du client, succès ou échec ;
5. répond : succès -> fichiers + récapitulatif à l'adresse « résultat » du
   point de vente si elle est configurée (Table de correspondance), sinon à
   l'adresse d'origine ; échec (mapping manquant...) -> alerte interne avec
   le détail, jamais envoyée au client (cohérent avec le blocage strict déjà
   en place ailleurs) ;
6. marque le mail source comme lu.

Ce module ne dépend d'aucun SDK Graph concret : `graph` n'importe quoi
d'objet exposant les méthodes utilisées ci-dessous (cf. core.graph_client.
GraphClient) — ce qui permet de tester toute cette orchestration avec un
faux client, sans réseau ni tenant Azure réel.
"""
from __future__ import annotations

import os

from core.client_store import list_clients
from core.converter import convert
from core.email_ingest import EmailIngestError, identifier_source
from core.history_store import record_conversion
from core.lightspeed_parser import LightspeedParseError, parse_lightspeed_export
from core.mapping_store import find_pdv, load_mappings
from core.pennylane_export import build_pennylane_csv
from core.timezone import now_local

SUPPORTED_EXTENSIONS = (".xls", ".xlsx", ".csv")


def _extension_supportee(filename: str) -> bool:
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def _adresse_alerte_interne() -> str | None:
    return os.environ.get("LSPENNYLANE_ALERTE_INTERNE") or None


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
    to_addresses = [r["emailAddress"]["address"] for r in message.get("toRecipients", [])]
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

    adresse_cible = to_addresses[0] if to_addresses else None
    for fichier in fichiers:
        _traiter_piece_jointe(graph, mailbox, adresse_cible, fichier["name"], fichier["content"])

    graph.mark_as_read(mailbox, message["id"])


def _traiter_piece_jointe(graph, mailbox: str, adresse_cible: str | None, filename: str, raw: bytes) -> None:
    try:
        if not adresse_cible:
            raise EmailIngestError(f"« {filename} » : mail sans destinataire exploitable.")
        source = identifier_source(adresse_cible, filename)
    except EmailIngestError as exc:
        _alerter(graph, mailbox, sujet=f"Export LightSpeed non identifié — {filename}", detail=str(exc))
        return

    try:
        export = parse_lightspeed_export(raw, filename)
    except LightspeedParseError as exc:
        _alerter(
            graph, mailbox,
            sujet=f"Export LightSpeed illisible — {source.client_id}/{source.code_pdv} — {filename}",
            detail=str(exc),
        )
        return

    # Si la période n'a pas pu être déduite du nom de fichier (source.avertissement
    # renseigné), on retombe sur la date du jour de traitement pour la pièce comptable ;
    # l'avertissement est repris dans l'alerte en cas d'échec plus bas, à vérifier manuellement.
    mappings = load_mappings(source.client_id)
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
    record_conversion(source.client_id, res, raw, csv_bytes, horodatage)

    if res.sans_erreur:
        # adresse_resultat (Table de correspondance > Points de vente) permet de renvoyer
        # ailleurs qu'à l'adresse de réception (ex. la comptable plutôt que la boîte
        # partagée elle-même) ; vide par défaut -> comportement historique inchangé.
        pdv = find_pdv(mappings, source.code_pdv)
        adresse_resultat = ((pdv or {}).get("adresse_resultat") or "").strip() or adresse_cible
        _envoyer_resultat(graph, mailbox, adresse_resultat, source, res, raw, csv_bytes)
    else:
        detail = "\n".join(res.erreurs)
        if source.avertissement:
            detail = f"{source.avertissement}\n{detail}"
        _alerter(
            graph, mailbox,
            sujet=f"Échec de conversion LightSpeed → Pennylane — {source.client_id}/{source.code_pdv} — {filename}",
            detail=detail,
        )


def _envoyer_resultat(graph, mailbox, adresse_resultat, source, res, raw: bytes, csv_bytes: bytes) -> None:
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
        # adresse_resultat = adresse_resultat du point de vente (Table de correspondance)
        # si renseignée, sinon l'adresse de réception d'origine (fallback résolu par
        # l'appelant, jamais l'alerte interne) — cf. docstring du module.
        to_addresses=[adresse_resultat],
        attachments=[(res.source_filename, raw), (f"import_pennylane_{res.point_de_vente}.csv", csv_bytes)],
    )


def _alerter(graph, mailbox: str, sujet: str, detail: str) -> None:
    destinataire = _adresse_alerte_interne()
    if not destinataire:
        return  # aucune adresse d'alerte configurée : rien à envoyer, l'historique/les logs font foi
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
