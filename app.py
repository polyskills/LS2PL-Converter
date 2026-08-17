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
import streamlit.components.v1 as components

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
    /* Espace libre au-dessus du titre de chaque page : Streamlit réserve 96px
    par défaut (place pour un en-tête qu'on n'utilise pas ici), largement plus
    que les 60px de la barre d'outils (Deploy...) qui la surplombe. Réduit à
    48px - juste assez pour ne pas passer sous cette barre. */
    div[data-testid="stMainBlockContainer"] {
        padding-top: 3rem;
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
    /* Sélecteur de client remonté au-dessus du menu de navigation, SANS
    déplacer le menu lui-même : Streamlit place stSidebarNav à une position
    fixe (toujours juste après le logo), quel que soit l'ordre des appels
    st.sidebar dans le script - un réordonnancement flex du conteneur entier
    déplacerait aussi le menu selon le contenu de CHAQUE page (ex. la liste
    de documents de la page Documentation, ajoutée au même conteneur), ce
    qui le ferait changer de place d'une page à l'autre. Le sélecteur est
    donc sorti du flux normal (position: absolute, ciblé par la classe
    "st-key-<key>" que Streamlit ajoute au conteneur d'un widget nommé) et
    positionné à l'endroit voulu ; une marge est ajoutée en haut du menu pour
    lui laisser la place sans chevauchement. Le pied de page (même
    conteneur partagé) est sorti du flux de la même façon, en position: fixed
    tout en bas, indépendamment du contenu de la page. */
    .st-key-client_id_selector {
        position: absolute;
        top: 108px;
        left: 0;
        width: 100%;
        box-sizing: border-box;
        padding: 0 20px;
        z-index: 1;
    }
    div[data-testid="stSidebarNav"] {
        margin-top: 56px;
    }
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

# Groupe "Documentation" replié par défaut au chargement : Streamlit ne propose
# aucun réglage Python pour l'état initial (déplié/replié) d'un groupe de menu,
# seul un clic sur son en-tête le replie, côté navigateur uniquement (pas de
# rerun ni de session_state associés). Un clic simulé au premier chargement
# reproduit ce geste ; le drapeau posé sur window.parent (persistant tant que
# l'onglet reste ouvert, contrairement à l'iframe du composant qui est
# recréée à chaque rerun) évite de re-replier le groupe si l'utilisateur l'a
# rouvert entre-temps.
components.html(
    r"""
    <script>
    function replierDocumentationUneFois() {
        if (window.parent.__lsPennylaneDocReplie) return;
        const doc = window.parent.document;
        const entetes = doc.querySelectorAll('[data-testid="stNavSectionHeader"]');
        for (const entete of entetes) {
            if (entete.textContent.trim().startsWith("Documentation")) {
                entete.click();
                window.parent.__lsPennylaneDocReplie = true;
                return;
            }
        }
    }
    new MutationObserver(replierDocumentationUneFois).observe(window.parent.document.body, {
        childList: true, subtree: true,
    });
    replierDocumentationUneFois();
    </script>
    """,
    height=0,
)

# Pied de page du menu latéral, personnalisable page Réglages : appelé après
# pg.run() pour apparaître tout en bas, sous le contenu propre à chaque page.
render_footer_sidebar()
