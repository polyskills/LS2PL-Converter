"""
Réglages ne relevant ni de la table de correspondance métier (comptes,
points de vente...) ni de la fiche client elle-même : paramètres généraux
de conversion et configuration de la réception automatique des exports par
mail, toujours propres au client sélectionné.
"""
from __future__ import annotations

import streamlit as st

from core.client_store import get_client, set_email_config
from core.mapping_store import load_mappings, save_mappings
from core.ui_common import select_client

client_id = select_client()

st.title("⚙️ Réglages")

if client_id is None:
    st.info("Créez un client (page **Clients**) avant de pouvoir régler ses paramètres.")
    st.stop()

mappings = load_mappings(client_id)
client = get_client(client_id)

st.subheader("Paramètres généraux de conversion")
st.caption("Réglages appliqués à toutes les conversions de ce client.")
params = mappings.get("parametres", {})
c1, c2 = st.columns(2)
with c1:
    code_journal = st.text_input("Code journal par défaut", value=params.get("code_journal", "VT"))
    code_pays = st.text_input("Code pays du compte", value=params.get("code_pays", "FR"))
    devise = st.text_input("Devise", value=params.get("devise", "EUR"))
    famille = st.text_input(
        "Famille analytique par défaut (si non précisée ligne par ligne)",
        value=params.get("famille_categorie_analytique", "POINT_DE_VENTE"),
    )
with c2:
    compte_ecart = st.text_input("Compte d'écart / report (équilibrage)", value=params.get("compte_ecart", "471000"))
    libelle_ecart = st.text_input(
        "Libellé du compte d'écart", value=params.get("libelle_compte_ecart", "Compte d'attente - écart de report LightSpeed")
    )
    tolerance = st.number_input(
        "Tolérance de rapprochement du report (€)",
        value=float(params.get("tolerance_equilibrage", 0.02)),
        step=0.01,
        format="%.2f",
    )

if st.button("💾 Enregistrer les paramètres généraux", type="primary"):
    save_mappings(
        client_id,
        {
            **mappings,
            "parametres": {
                "code_journal": code_journal,
                "code_pays": code_pays,
                "devise": devise,
                "famille_categorie_analytique": famille,
                "compte_ecart": compte_ecart,
                "libelle_compte_ecart": libelle_ecart,
                "tolerance_equilibrage": tolerance,
            },
        },
    )
    st.success("Paramètres généraux enregistrés.")

st.divider()
st.subheader("Réception automatique des exports LightSpeed par mail")
st.caption(
    "La boîte mail vit dans le tenant M365 du client. Une adresse dédiée par point de vente se "
    "paramètre dans « Table de correspondance » ; ici, uniquement le tenant et la boîte mail à "
    "interroger. Laisser vide désactive le fetch automatique pour ce client. "
    "Voir `deploy/windows/README.md` pour la mise en place complète (app Azure AD, consentement admin, service)."
)
ce1, ce2 = st.columns(2)
tenant_id = ce1.text_input(
    "Tenant ID Azure AD du client",
    value=client.get("email_tenant_id", ""),
    help="Identifiant du tenant M365 du client (Entra ID > Vue d'ensemble). "
    "Nécessite le consentement admin du client sur l'app Azure AD Polyskills.",
)
mailbox = ce2.text_input(
    "Boîte mail à interroger (UPN)",
    value=client.get("email_mailbox", ""),
    help="Boîte partagée recevant les adresses dédiées (ex. rapport_ls_paris_bar@...).",
)
if st.button("💾 Enregistrer la config mail"):
    set_email_config(client_id, tenant_id, mailbox)
    st.success("Config mail enregistrée.")
    st.rerun()
