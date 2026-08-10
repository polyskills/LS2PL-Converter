"""Gestion des clients (espaces isolés : référentiel + historique propres à chacun)."""
from __future__ import annotations

import streamlit as st

from core.client_store import create_client, list_clients, rename_client
from core.mapping_store import seed_with_examples
from core.ui_common import select_client

st.set_page_config(page_title="Clients", page_icon="👥", layout="wide")
st.title("👥 Clients")
st.caption(
    "Chaque client dispose de son propre référentiel (comptes, points de vente, codes "
    "analytiques) et de son propre historique de conversions, totalement isolés des autres. "
    "⚠️ Aucune authentification n'est en place à ce stade : tous les utilisateurs de cette "
    "application voient tous les clients listés ici."
)

select_client()

st.divider()
st.subheader("Créer un nouveau client")
with st.form("nouveau_client"):
    c1, c2 = st.columns([3, 2])
    nom = c1.text_input("Nom du client", placeholder="Ex : Louvre Gourmet")
    avec_exemples = c2.checkbox(
        "Pré-remplir avec un référentiel d'exemple",
        value=False,
        help="À réserver aux tests : le référentiel d'exemple ne correspond pas au plan "
        "comptable réel du client et doit être entièrement revérifié avant usage en production.",
    )
    submitted = st.form_submit_button("Créer le client", type="primary")
    if submitted:
        if not nom.strip():
            st.error("Le nom du client est obligatoire.")
        else:
            client = create_client(nom.strip())
            if avec_exemples:
                seed_with_examples(client["id"])
            st.session_state["client_id"] = client["id"]
            st.success(f"Client « {client['nom']} » créé.")
            st.rerun()

st.divider()
st.subheader("Clients existants")
clients = list_clients()
if not clients:
    st.info("Aucun client pour l'instant.")
else:
    for c in clients:
        with st.expander(f"🏢 {c['nom']}  ·  `{c['id']}`"):
            new_name = st.text_input("Renommer", value=c["nom"], key=f"rename_{c['id']}")
            if st.button("Enregistrer le nouveau nom", key=f"save_rename_{c['id']}"):
                rename_client(c["id"], new_name.strip())
                st.success("Nom mis à jour.")
                st.rerun()
