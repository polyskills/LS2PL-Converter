"""
Point d'entrée / contrôleur de navigation de l'application.

Structure via st.navigation (Streamlit >= 1.36) plutôt que la découverte
automatique du dossier pages/ : permet de donner un titre propre à chaque
page dans la barre latérale (au lieu du nom de fichier) et de regrouper les
pages d'administration sous un même menu. st.set_page_config ne doit être
appelé qu'ici, jamais dans les pages elles-mêmes.
"""
from __future__ import annotations

import streamlit as st

from core.ui_common import render_client_selector, render_footer_sidebar

st.set_page_config(page_title="LightSpeed → Pennylane", page_icon="🧾", layout="wide")

st.logo("assets/logo.png", size="large")

# st.logo() plafonne la hauteur de l'image (32px max, quel que soit `size`) : bien
# trop petit pour ce logo. C'est pourtant le seul mécanisme Streamlit qui place une
# image AU-DESSUS du menu de navigation (celui-ci occupe toujours le haut de la
# barre latérale, peu importe l'ordre des appels st.sidebar dans le script). On
# garde donc st.logo() pour le placement, et on lève sa limite de taille par CSS.
#
# Largeur du menu latéral fixée à 250px : mesurée dans un navigateur réel comme
# la largeur minimale contenant, sans retour à la ligne ni troncature, le plus
# long intitulé de navigation ("Table de correspondance", police 14px par
# défaut Streamlit) + son icône + le padding du menu. Repli et redimensionnement
# désactivés (bouton de repli et poignée de redimensionnement masqués) : cette
# largeur doit rester fixe.
st.markdown(
    """
    <style>
    div[data-testid="stSidebarHeader"] {
        height: auto;
        padding-bottom: 0.75rem;
        justify-content: center;
    }
    img[data-testid="stSidebarLogo"] {
        max-height: none;
        height: auto;
        width: 90%;
        max-width: 90%;
        display: block;
        margin: 0 auto;
    }
    section[data-testid="stSidebar"] {
        width: 250px !important;
        min-width: 250px !important;
        max-width: 250px !important;
    }
    /* Poignée de redimensionnement : seul enfant direct du menu latéral sans
    data-testid (le contenu, lui, est dans stSidebarContent). */
    section[data-testid="stSidebar"] > div:not([data-testid="stSidebarContent"]) {
        display: none !important;
    }
    div[data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
    /* Sélecteur de client remonté au-dessus du menu de navigation : Streamlit
    place stSidebarNav à une position fixe, quel que soit l'ordre des appels
    st.sidebar dans le script (même avant st.navigation()) - seul un
    réordonnancement flex CSS permet de le faire passer visuellement après
    le contenu ajouté par l'app (sélecteur de client, cf. core.ui_common.
    render_client_selector). Le pied de page (même conteneur) est retiré du
    flux par position: fixed ci-dessous pour ne pas être entraîné vers le
    haut avec le reste.  */
    div[data-testid="stSidebarContent"] {
        display: flex;
        flex-direction: column;
    }
    div[data-testid="stSidebarHeader"] { order: 0; }
    div[data-testid="stSidebarUserContent"] { order: 1; }
    div[data-testid="stSidebarNav"] { order: 2; }
    .ls-pennylane-sidebar-footer {
        position: fixed;
        left: 0;
        bottom: 0.75rem;
        width: 250px;
        box-sizing: border-box;
        padding: 0 1.5rem;
        text-align: center;
        font-size: 0.8rem;
        color: rgba(49, 51, 63, 0.6);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Sélecteur de client remonté au-dessus du menu de navigation (Streamlit ne
# laisse pas d'autre moyen : le menu de navigation occupe toujours le haut de
# la barre latérale une fois affiché, quel que soit l'ordre des appels
# st.sidebar une fois la page en cours d'exécution - seul un appel AVANT
# st.navigation()/pg.run() apparaît au-dessus). Liste déroulante seule, sans
# intitulé visible.
render_client_selector()

pages = {
    "Conversion": [
        st.Page("pages/converter.py", title="Convertisseur", icon="🧾", default=True),
    ],
    "Gestion": [
        st.Page("pages/clients.py", title="Clients", icon="👥"),
        st.Page("pages/mapping.py", title="Table de correspondance", icon="🗂️"),
        st.Page("pages/historique.py", title="Historique", icon="🕓"),
    ],
    "Paramètres": [
        st.Page("pages/reglages.py", title="Réglages", icon="⚙️"),
    ],
    "Documentation": [
        st.Page("pages/documentation.py", title="Documentation", icon="📚"),
    ],
}

pg = st.navigation(pages)
pg.run()

# Pied de page du menu latéral, personnalisable page Réglages : appelé après
# pg.run() pour apparaître tout en bas, sous le contenu propre à chaque page.
render_footer_sidebar()
