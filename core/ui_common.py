"""Éléments d'interface partagés entre les pages (sélecteur de client)."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core.bootstrap import ensure_defaults
from core.client_store import create_client, list_clients
from core.version_info import get_version_info


def show_version_footer() -> None:
    """Affiche, en bas de la barre latérale, le commit Git réellement en cours
    d'exécution — pour vérifier après un déploiement que c'est bien la dernière
    version poussée qui tourne, plutôt que de le supposer."""
    info = get_version_info()
    with st.sidebar:
        st.divider()
        if info["hash"]:
            date_str = info["date"]
            try:
                date_str = dt.datetime.fromisoformat(info["date"]).strftime("%d/%m/%Y %H:%M")
            except (TypeError, ValueError):
                pass
            st.caption(
                f"🔖 Version déployée : `{info['hash']}`"
                + (" *(modifs. non commitées)*" if info["dirty"] else "")
                + f"\n\nBranche `{info['branch']}` · {date_str}\n\n> {info['message']}"
            )
        else:
            st.caption("🔖 Version : information Git indisponible sur cet hébergement.")

        if st.button("🔄 Vider le cache et recharger", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()


def select_client() -> str | None:
    """Affiche le sélecteur de client dans la barre latérale et retourne le
    client actuellement sélectionné (client_id), ou None si aucun client
    n'existe encore.

    ⚠️ Aucune authentification n'est appliquée à ce stade (usage interne,
    équipe restreinte) : tout utilisateur de l'app voit tous les clients.
    """
    ensure_defaults()
    clients = list_clients()
    selected: str | None = None

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
        else:
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

    show_version_footer()
    return selected
