"""
Consolidation LightSpeed
========================
Croise les deux rapports Lightspeed Back Office — « Tickets » et
« Transactions » — pour produire un classeur de synthèse du CA par période de
service (SYNTHESE, JOUR x PERIODE, ROTATIONS, DUREE PRESENCE, DONNEES,
TICKETS, ANOMALIES).

Indépendante de la conversion comptable : elle ne consulte pas le référentiel
du client et ne produit aucune écriture Pennylane. Les deux traitements
partagent en revanche le même applicatif, le même mécanisme d'archivage et le
même client sélectionné.

L'historique de ces consolidations se consulte depuis la page « Historique »
rangée sous celle-ci dans le menu, distincte de celle des conversions.
"""
from __future__ import annotations

import streamlit as st

from core.history_store import record_consolidation
from core.lightspeed_synthese import (
    SITES,
    SyntheseError,
    classer_fichiers,
    construire_synthese,
    deviner_site,
)
from core.timezone import now_local
from core.consolidation_sas import (
    DELAI_ALERTE_HEURES,
    est_complet,
    lister as lister_en_attente,
    rapport_manquant,
)
from core.ui_common import render_bouton_releve_mails, select_client, styliser_zone_de_depot

def _relancer_paires(client_id: str) -> int:
    """Retente toutes les paires complètes en échec de ce client.

    Le client Graph n'est construit que si la réception mail est configurée :
    la consolidation aboutie doit alors repartir par mail comme elle l'aurait
    fait automatiquement. Sans configuration, la relance fonctionne quand même
    — le résultat est archivé dans l'historique, simplement pas envoyé."""
    from core.client_store import get_client
    from core.email_poller import _identifiants_azure, reprendre_paires_en_echec

    client = get_client(client_id) or {}
    graph = None
    mailbox = client.get("email_mailbox") or ""
    identifiants = _identifiants_azure(client) if client.get("email_tenant_id") and mailbox else None
    if identifiants:
        from core.graph_client import GraphClient

        graph = GraphClient(
            tenant_id=client["email_tenant_id"], client_id=identifiants[0], client_secret=identifiants[1]
        )
    return reprendre_paires_en_echec(graph, mailbox, client_id)


client_id = select_client()

st.title("📊 Consolidation LightSpeed")
st.caption(
    "Importez les deux rapports Lightspeed Back Office d'une même période, associez chaque "
    "fichier à son rapport et à son site, puis générez le classeur de synthèse du CA par "
    "période de service. Plusieurs jours peuvent être traités d'un coup : les doublons sont "
    "éliminés."
)

if client_id is None:
    st.info("Créez un client (menu latéral, ou page **Clients**) avant de pouvoir lancer une consolidation.")
    st.stop()

render_bouton_releve_mails(
    client_id,
    contexte="Les rapports de consolidation reçus sont mis en attente jusqu'à ce que leur binôme "
    "arrive — Tickets attend Transactions et réciproquement — puis la synthèse est produite et "
    "renvoyée automatiquement.",
    cle="releve_consolidation",
)

# Rapports reçus par mail et pas encore consolidés. Deux situations très
# différentes, d'où deux blocs : ceux qui attendent leur binôme (normal), et
# ceux dont la paire est complète mais dont la consolidation a échoué.
en_attente_total = lister_en_attente(client_id)
attente_binome = [e for e in en_attente_total if not est_complet(e)]
en_echec = [e for e in en_attente_total if est_complet(e)]


def _depose_le(etat: dict) -> str:
    return min((r.get("horodatage", "") for r in etat.get("rapports", {}).values()), default="")


if attente_binome:
    with st.expander(f"⏳ {len(attente_binome)} rapport(s) en attente de leur binôme", expanded=False):
        st.caption(
            f"Un rapport resté seul plus de {DELAI_ALERTE_HEURES} h déclenche une alerte interne. "
            "Il est conservé : un envoi tardif complète la paire et lance la consolidation."
        )
        st.dataframe(
            [
                {
                    "Point de vente": e.get("code_pdv", ""),
                    "Période": f"{e.get('date_debut') or '?'} → {e.get('date_fin') or '?'}",
                    "Reçu": ", ".join(sorted(e.get("rapports", {}))),
                    "En attente de": rapport_manquant(e),
                    "Depuis": _depose_le(e),
                }
                for e in attente_binome
            ],
            use_container_width=True,
            hide_index=True,
        )

if en_echec:
    with st.expander(f"❌ {len(en_echec)} paire(s) complète(s) dont la consolidation a échoué", expanded=True):
        st.caption(
            "Les deux rapports sont là, mais la consolidation n'a pas abouti. Les fichiers sont "
            "conservés : la cause se corrige presque toujours dans la Table de correspondance "
            "(site de consolidation du point de vente, référentiel comptable). Chaque paire est "
            "retentée automatiquement à chaque cycle de relève — le bouton ci-dessous évite "
            "d'attendre le prochain."
        )
        for e in en_echec:
            periode = f"{e.get('date_debut') or '?'} → {e.get('date_fin') or '?'}"
            motif = (e.get("derniere_erreur") or {}).get("motif")
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{e.get('code_pdv', '')}** — {periode}  ·  reçue le {_depose_le(e)}")
            if motif:
                c1.caption(f"Dernier motif : {motif}")
            if c2.button("🔄 Relancer", key=f"relancer_{e['cle']}"):
                with st.spinner("Nouvelle tentative..."):
                    reussies = _relancer_paires(client_id)
                if reussies:
                    st.success(f"{reussies} consolidation(s) menée(s) à bien — voir « Historique ».")
                else:
                    st.error("La consolidation échoue toujours. Le motif ci-dessus indique quoi corriger.")
                st.rerun()

st.subheader("1. Importer les rapports Tickets et Transactions")
styliser_zone_de_depot()
uploaded_files = st.file_uploader(
    "Rapports Lightspeed Tickets et Transactions (.xls / .xlsx / .csv)",
    type=["xls", "xlsx", "csv"],
    accept_multiple_files=True,
    key="conso_uploader",
)

# Même précaution que la page Convertisseur : le résultat conservé en session
# pour survivre aux reruns des widgets devient trompeur dès que le jeu de
# fichiers change. On le purge sur changement de signature plutôt que
# d'attendre un nouveau clic.
signature = tuple(sorted((uf.name, uf.size) for uf in uploaded_files)) if uploaded_files else ()
if st.session_state.get("conso_signature") != signature:
    st.session_state.pop("conso_resultat", None)
    st.session_state["conso_signature"] = signature

if not uploaded_files:
    # Même invitation qu'en bas de la page Convertisseur quand aucun fichier
    # n'est déposé : la page ne doit jamais s'arrêter en silence.
    st.info("Déposez les rapports Tickets et Transactions d'une même période pour démarrer.")
    st.stop()

par_nom = {uf.name: uf for uf in uploaded_files}
noms = list(par_nom)
sugg_tickets, sugg_transactions, inconnus = classer_fichiers(noms)

st.subheader("2. Associer chaque fichier à son rapport et au site")
st.caption(
    "Pré-rempli d'après le nom des fichiers (`..._tickets_...` / `..._transactions_...`), "
    "comme le point de vente l'est page Convertisseur. Corrigez si un export a été renommé."
)
if inconnus:
    st.warning(
        "Fichier(s) non reconnus d'après leur nom, à répartir manuellement : "
        + ", ".join(f"**{n}**" for n in inconnus)
    )

c1, c2 = st.columns(2)
choix_tickets = c1.multiselect("Rapport(s) « Tickets »", options=noms, default=sugg_tickets)
choix_transactions = c2.multiselect("Rapport(s) « Transactions »", options=noms, default=sugg_transactions)

en_double = sorted(set(choix_tickets) & set(choix_transactions))
if en_double:
    st.error(
        "Un même fichier ne peut pas être à la fois Tickets et Transactions : "
        + ", ".join(f"**{n}**" for n in en_double)
    )

# Le nom des exports porte la source ("..._barutopic_tickets_...") : on s'en
# sert pour pré-sélectionner le site, sans jamais décider à la place de
# l'utilisateur — c'est la valeur choisie ici, et elle seule, qui détermine
# les périodes de service appliquées au calcul.
site_suggere = deviner_site(noms)
site = st.selectbox(
    "Site (détermine les périodes de service)",
    options=list(SITES),
    index=list(SITES).index(site_suggere) if site_suggere else 0,
    help="Les plages horaires de chaque période dépendent du site : "
    + " · ".join(f"{s} : {', '.join(p for p, *_ in SITES[s]['periodes'])}" for s in SITES),
)
if site_suggere:
    st.caption("Site déduit du nom des fichiers déposés — à corriger si besoin.")

pret = bool(choix_tickets) and bool(choix_transactions) and not en_double
if not pret and not en_double:
    st.info("Sélectionnez au moins un rapport de chaque type pour lancer la consolidation.")

st.divider()
st.subheader("3. Consolidation et contrôle du chiffre d'affaires")

if st.button("🔄 Lancer la consolidation", type="primary", disabled=not pret):
    tickets = [(n, par_nom[n].getvalue()) for n in choix_tickets]
    transactions = [(n, par_nom[n].getvalue()) for n in choix_transactions]
    try:
        res = construire_synthese(tickets, transactions, site)
    except SyntheseError as e:
        st.error(f"❌ {e}")
        st.stop()
    # Archivée immédiatement, avant même d'être téléchargée : l'historique doit
    # garder la trace de ce qui a été produit, pas seulement de ce qui a été
    # récupéré — même logique que pour les conversions.
    record_consolidation(client_id, res, tickets + transactions, now_local().strftime("%Y-%m-%d %H:%M:%S"))
    st.session_state["conso_resultat"] = res

res = st.session_state.get("conso_resultat")
if res is None:
    st.stop()

st.caption(f"{res.site} — {res.periode_libelle} · {res.nb_tickets} tickets · {res.nb_lignes} lignes de transaction")

m1, m2, m3, m4 = st.columns(4)
m1.metric("CA TTC", f"{res.ca_ttc:,.2f} €".replace(",", " "))
m2.metric("CA HT", f"{res.ca_ht:,.2f} €".replace(",", " "))
m3.metric("Couverts", f"{res.couverts:,}".replace(",", " "))
m4.metric(
    "Contrôle transactions / tickets",
    "Équilibré ✅" if res.sans_anomalie_bloquante else f"Écart {res.ecart_controle:+.2f} €",
    delta_color="off",
)

if res.sans_anomalie_bloquante:
    st.success(
        "✅ Le total des lignes de transaction correspond exactement au total des tickets : "
        "aucune vente perdue ni comptée deux fois."
    )
else:
    st.error(
        f"❌ Écart de {res.ecart_controle:+.2f} € entre le total des transactions et celui des tickets. "
        "Les deux rapports ne couvrent probablement pas exactement la même période — le classeur est "
        "généré quand même, mais ses totaux ne sont pas fiables en l'état."
    )

a_verifier = res.anomalies_a_verifier
if a_verifier:
    with st.expander(f"⚠️ {len(a_verifier)} point(s) à vérifier", expanded=not res.sans_anomalie_bloquante):
        for libelle, valeur, detail in a_verifier:
            st.warning(f"**{libelle}** — {valeur}\n\n{detail}")
else:
    st.info("Aucun point à vérifier signalé : groupes tous mappés, aucun ticket annulé, périodes cohérentes.")

st.caption(
    "📁 Cette consolidation a été archivée dans l'historique de ce client "
    "(page « Historique », sous Consolidation)."
)

st.divider()
st.subheader("4. Télécharger le classeur de synthèse")
jour_fname = f"{res.jours[0]:%Y%m%d}" if res.jours else "sansdate"
if len(res.jours) > 1:
    jour_fname += f"_{res.jours[-1]:%Y%m%d}"
st.download_button(
    "⬇️ Télécharger le classeur de synthèse (.xlsx)",
    data=res.classeur,
    file_name=f"synthese_{res.site.lower()}_{jour_fname}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
st.caption(
    "Les onglets de synthèse sont construits en formules `SUMIFS` sur les onglets DONNEES et "
    "TICKETS : le classeur reste recalculable, filtrable et vérifiable dans Excel."
)
