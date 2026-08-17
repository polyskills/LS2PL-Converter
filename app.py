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
        width: 100%;
        max-width: 100%;
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
    </style>
    """,
    unsafe_allow_html=True,
)

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
