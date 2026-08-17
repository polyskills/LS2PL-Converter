"""Gestion des clients (espaces isolés : référentiel + historique propres à chacun)."""
from __future__ import annotations

import streamlit as st

from core.client_store import create_client, delete_client, list_clients, rename_client
from core.ui_common import select_client

st.title("👥 Clients")
st.caption(
    "Chaque client dispose de son propre référentiel (comptes, points de vente, codes "
    "analytiques) et de son propre historique de conversions, totalement isolés des autres. "
    "⚠️ Aucune authentification n'est en place à ce stade : tous les utilisateurs de cette "
    "application voient tous les clients listés ici. La réception automatique des exports "
    "par mail se paramètre page **Réglages**."
)

select_client()

st.divider()
st.subheader("Créer un nouveau client")
with st.form("nouveau_client"):
    nom = st.text_input("Nom du client", placeholder="Ex : Louvre Gourmet")
    submitted = st.form_submit_button("Créer le client", type="primary")
    if submitted:
        if not nom.strip():
            st.error("Le nom du client est obligatoire.")
        else:
            client = create_client(nom.strip())
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

            st.divider()
            _cle_confirmation = f"confirmation_suppression_{c['id']}"
            if st.button("🗑️ Supprimer ce client", key=f"delete_{c['id']}"):
                st.session_state[_cle_confirmation] = True
            if st.session_state.get(_cle_confirmation):
                st.warning(
                    f"⚠️ Ceci supprime **définitivement** « {c['nom']} » et tout son contenu "
                    "(référentiel, historique de conversions, fichiers archivés). Cette action "
                    "est irréversible — pensez à faire une sauvegarde (page **Réglages**) avant "
                    "si un doute subsiste."
                )
                cv1, cv2, _ = st.columns([1, 1, 4])
                if cv1.button("✅ Oui, supprimer", key=f"confirm_delete_{c['id']}", type="primary"):
                    delete_client(c["id"])
                    st.session_state.pop(_cle_confirmation, None)
                    if st.session_state.get("client_id") == c["id"]:
                        st.session_state.pop("client_id", None)
                    st.success(f"Client « {c['nom']} » supprimé.")
                    st.rerun()
                if cv2.button("Annuler", key=f"cancel_delete_{c['id']}"):
                    st.session_state.pop(_cle_confirmation, None)
                    st.rerun()
