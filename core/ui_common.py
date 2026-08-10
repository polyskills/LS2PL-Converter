"""Éléments d'interface partagés entre les pages (sélecteur de client)."""
from __future__ import annotations

import streamlit as st

from core.client_store import create_client, list_clients


def select_client() -> str | None:
    """Affiche le sélecteur de client dans la barre latérale et retourne le
    client actuellement sélectionné (client_id), ou None si aucun client
    n'existe encore.

    ⚠️ Aucune authentification n'est appliquée à ce stade (usage interne,
    équipe restreinte) : tout utilisateur de l'app voit tous les clients.
    """
    clients = list_clients()

    with st.sidebar:
        st.markdown("### 🏢 Client")
        if not clients:
            st.warning("Aucun client paramétré.")
            with st.form("creation_client_rapide"):
                nom = st.text_input("Nom du client")
                if st.form_submit_button("Créer ce client") and nom.strip():
                    c = create_client(nom.strip())
                    st.session_state["client_id"] = c["id"]
                    st.rerun()
            st.caption("Ou rendez-vous sur la page **Clients** pour plus d'options.")
            return None

        ids = [c["id"] for c in clients]
        noms = {c["id"]: c["nom"] for c in clients}
        current = st.session_state.get("client_id")
        index = ids.index(current) if current in ids else 0
        selected = st.selectbox(
            "Client actif",
            options=ids,
            index=index,
            format_func=lambda cid: noms.get(cid, cid),
            key="client_id_selector",
        )
        st.session_state["client_id"] = selected
        st.caption(f"ID technique : `{selected}`")
        return selected
