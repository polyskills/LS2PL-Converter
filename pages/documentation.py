"""
Documentation interne : affiche les fichiers Markdown stockés dans docs/,
pour consultation directe dans l'application sans avoir à ouvrir le dépôt
Git. Toute nouvelle documentation d'équipe (checklist, fonctionnement d'une
fonctionnalité...) doit être déposée en .md dans ce dossier pour apparaître
ici automatiquement — rien à coder ni à enregistrer ailleurs.
"""
from __future__ import annotations

import os

import streamlit as st

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")


def _list_docs() -> list[str]:
    """Alphabétique, sauf mise_en_route.md toujours en tête : c'est le point
    d'entrée logique (checklist de mise en route) quand on ouvre cette page."""
    if not os.path.isdir(DOCS_DIR):
        return []
    fichiers = [f for f in os.listdir(DOCS_DIR) if f.lower().endswith(".md")]
    return sorted(fichiers, key=lambda f: (f.lower() != "mise_en_route.md", f.lower()))


def _titre(nom_fichier: str) -> str:
    """Le premier titre '# ...' du fichier sert de libellé, sinon son nom."""
    try:
        with open(os.path.join(DOCS_DIR, nom_fichier), "r", encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if ligne.startswith("# "):
                    return ligne[2:].strip()
    except OSError:
        pass
    return nom_fichier


st.title("📚 Documentation")

fichiers = _list_docs()
if not fichiers:
    st.info(
        "Aucun fichier de documentation trouvé. Déposez des fichiers `.md` dans le dossier "
        "`docs/` du dépôt pour qu'ils apparaissent ici."
    )
    st.stop()

libelles = {f: _titre(f) for f in fichiers}

with st.sidebar:
    st.markdown("### 📚 Documents")
    selection = st.radio(
        "Choisir un document",
        options=fichiers,
        format_func=lambda f: libelles[f],
        label_visibility="collapsed",
        key="doc_selectionnee",
    )

with open(os.path.join(DOCS_DIR, selection), "r", encoding="utf-8") as f:
    contenu = f.read()

st.caption(f"📄 `docs/{selection}`")
st.divider()
st.markdown(contenu)
