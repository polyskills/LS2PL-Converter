"""Éléments d'interface partagés entre les pages (sélecteur de client)."""
from __future__ import annotations

import html

import streamlit as st

from core.app_config import get_footer_sidebar
from core.bootstrap import ensure_defaults
from core.client_store import create_client, list_clients
from core.timezone import to_local
from core.version_info import get_version_info


def render_infos_techniques(client_id: str | None) -> None:
    """Affiche l'ID technique du client actif, le commit Git réellement en
    cours d'exécution (pour vérifier après un déploiement que c'est bien la
    dernière version poussée qui tourne, plutôt que de le supposer) et le
    bouton de purge du cache. Anciennement dans la barre latérale de chaque
    page ; rassemblé dans un espace dédié de la page Réglages pour désencombrer
    le menu latéral."""
    if client_id is not None:
        st.caption(f"ID technique du client actif : `{client_id}`")

    info = get_version_info()
    if info["hash"]:
        date_str = info["date"]
        local_dt = to_local(info["date"]) if info["date"] else None
        if local_dt is not None:
            date_str = local_dt.strftime("%d/%m/%Y %H:%M") + " (heure de Paris)"
        st.caption(
            f"🔖 Version déployée : `{info['hash']}`"
            + (" *(modifs. non commitées)*" if info["dirty"] else "")
            + f"\n\nBranche `{info['branch']}` · {date_str}\n\n> {info['message']}"
        )
    else:
        st.caption("🔖 Version : information Git indisponible sur cet hébergement.")

    if st.button("🔄 Vider le cache et recharger"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()


def render_client_selector() -> str | None:
    """Rendu unique du sélecteur de client (liste déroulante seule, sans
    intitulé visible), à appeler depuis app.py. Streamlit place le menu de
    navigation à une position fixe de la barre latérale, quel que soit
    l'ordre des appels st.sidebar dans le script (même avant st.navigation()) :
    le faire apparaître au-dessus nécessite donc en plus un réordonnancement
    CSS flex (order) sur les conteneurs de la barre latérale, posé dans
    app.py. Mémorise le choix dans st.session_state['client_id'], relu
    ensuite par select_client(). Ne rend rien si aucun client n'existe encore
    (select_client() affiche alors le formulaire de création rapide)."""
    ensure_defaults()
    clients = list_clients()
    if not clients:
        return None

    ids = [c["id"] for c in clients]
    noms = {c["id"]: c["nom"] for c in clients}
    current = st.session_state.get("client_id")
    index = ids.index(current) if current in ids else 0
    with st.sidebar:
        selected = st.selectbox(
            "Client actif",
            options=ids,
            index=index,
            format_func=lambda cid: noms.get(cid, cid),
            key="client_id_selector",
            label_visibility="collapsed",
        )
    st.session_state["client_id"] = selected
    return selected


def select_client() -> str | None:
    """Retourne le client actif choisi via le sélecteur en haut du menu
    latéral (render_client_selector, appelé une fois depuis app.py). Si aucun
    client n'existe encore, affiche ici le formulaire de création rapide.

    ⚠️ Aucune authentification n'est appliquée à ce stade (usage interne,
    équipe restreinte) : tout utilisateur de l'app voit tous les clients.
    """
    clients = list_clients()
    if clients:
        return st.session_state.get("client_id")

    with st.sidebar:
        st.warning("Aucun client paramétré.")
        with st.form("creation_client_rapide"):
            nom = st.text_input("Nom du client")
            if st.form_submit_button("Créer ce client") and nom.strip():
                c = create_client(nom.strip())
                st.session_state["client_id"] = c["id"]
                st.rerun()
        st.caption("Ou rendez-vous sur la page **Clients** pour plus d'options.")
    return None


def render_footer_sidebar() -> None:
    """Pied de page du menu latéral (texte personnalisable page Réglages,
    onglet Informations). Positionné en CSS (position: fixed, cf. app.py)
    plutôt que par simple ordre d'appel : le sélecteur de client remonté
    au-dessus du menu de navigation déplace, avec lui, tout le reste du
    contenu ajouté à la barre latérale (même conteneur Streamlit) — sans
    ce correctif, le pied de page serait entraîné vers le haut lui aussi."""
    texte = get_footer_sidebar()
    if texte:
        with st.sidebar:
            st.markdown(
                f'<div class="ls-pennylane-sidebar-footer">{html.escape(texte)}</div>',
                unsafe_allow_html=True,
            )
