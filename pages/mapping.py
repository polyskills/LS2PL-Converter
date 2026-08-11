"""
Page de paramétrage des tables de correspondance utilisées par la moulinette
de conversion LightSpeed → Pennylane, pour le client actuellement sélectionné.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.mapping_store import load_mappings, reset_to_empty, save_mappings, seed_with_examples
from core.ui_common import select_client


def _as_editable_df(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """st.data_editor ne sait pas proposer de bouton '+' d'ajout de ligne sur une
    liste Python vide : sans colonnes connues, il n'a rien à afficher. On force
    donc toujours un DataFrame avec les colonnes attendues, même à 0 ligne.
    reindex() (plutôt que juste indexer par la liste des colonnes) tolère aussi
    une colonne demandée mais absente de toutes les lignes existantes (ex. un
    champ ajouté après coup, comme "commentaires") sans lever de KeyError -
    mais une colonne ainsi créée de toutes pièces est en float64 (NaN), ce que
    TextColumn refuse ("not compatible... float"). Toutes nos colonnes sont du
    texte (y compris les codes numériques comme "70110010", traités comme des
    chaînes) : fillna("").astype(str) force donc explicitement le type texte
    partout, plutôt que de le laisser deviner par pandas."""
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).reindex(columns=columns).fillna("").astype(str)

client_id = select_client()

st.title("🗂️ Table de correspondance")
st.caption(
    "LightSpeed ne gère pas de code analytique : c'est la combinaison "
    "**compte comptable × point de vente × département** qui permet de le reconstituer. "
    "Paramétrez ici les tables utilisées par la conversion, propres au client sélectionné. "
    "Les réglages généraux (code journal, compte d'écart...) se trouvent page **Réglages**."
)

if client_id is None:
    st.stop()

mappings = load_mappings(client_id)

tab_pdv, tab_comptes, tab_departements, tab_analytique, tab_paiement, tab_tva = st.tabs(
    [
        "Points de vente",
        "Comptes de vente",
        "Départements LightSpeed",
        "Codes analytiques",
        "Contreparties de paiement",
        "TVA collectée",
    ]
)

with tab_pdv:
    st.markdown(
        "Liste des points de vente (sites, salles, activités...) rencontrés dans les exports LightSpeed. "
        "L'**adresse mail** est optionnelle : si elle est renseignée, tout export LightSpeed reçu "
        "automatiquement à cette adresse sera rattaché à ce point de vente (voir la moulinette de "
        "réception automatique). Elle doit être unique entre tous les clients."
    )
    edited_pdv_df = st.data_editor(
        _as_editable_df(mappings.get("points_de_vente", []), ["code", "libelle", "adresse_email", "commentaires"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_pdv",
        column_config={
            "code": st.column_config.TextColumn("Code point de vente", required=True),
            "libelle": st.column_config.TextColumn("Libellé", required=True),
            "adresse_email": st.column_config.TextColumn(
                "Adresse mail de réception (optionnelle)",
                help="Adresse dédiée qui reçoit l'export automatique LightSpeed de ce point de vente.",
            ),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_pdv = edited_pdv_df.dropna(how="all").fillna("").to_dict("records")

with tab_comptes:
    st.markdown(
        "**Référentiel des comptes de vente Pennylane** (plan comptable), indépendant de LightSpeed. "
        "Sert uniquement à proposer une liste de comptes valides (menu déroulant) dans les tables "
        "« Départements LightSpeed » et « Codes analytiques », pour éviter les erreurs de saisie — "
        "c'est *là-bas* que se fait le lien avec les catégories LightSpeed, pas ici."
    )
    edited_comptes_df = st.data_editor(
        _as_editable_df(mappings.get("comptes_de_vente", []), ["compte", "libelle_compte", "commentaires"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_comptes",
        column_config={
            "compte": st.column_config.TextColumn("Compte", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte", required=True),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_comptes = edited_comptes_df.dropna(how="all").fillna("").to_dict("records")
    comptes_options = [c["compte"] for c in edited_comptes if c.get("compte")]

with tab_departements:
    st.markdown(
        "Correspondance entre chaque **département LightSpeed** (colonne « Références comptables » "
        "de l'export — LightSpeed n'a pas de notion de catégorie distincte du département) et son "
        "**compte de vente** (choisi dans le référentiel de l'onglet précédent). Le **taux de TVA** "
        "ici est purement informatif : le taux réellement appliqué à chaque ligne vient du fichier "
        "LightSpeed lui-même, pas de cette table. Tout département rencontré dans un fichier importé "
        "et absent d'ici bloquera l'export ; un département présent mais sans compte choisi bloque "
        "également (mieux vaut bloquer que deviner)."
    )
    if not comptes_options:
        st.warning("Ajoutez d'abord des comptes dans l'onglet « Comptes de vente » pour pouvoir les choisir ici.")
    edited_departements_df = st.data_editor(
        _as_editable_df(
            mappings.get("departements", []),
            ["categorie_lightspeed", "compte", "taux_tva", "commentaires"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_departements",
        column_config={
            "categorie_lightspeed": st.column_config.TextColumn("Département LightSpeed", required=True),
            "compte": st.column_config.SelectboxColumn("Compte de vente", options=comptes_options),
            "taux_tva": st.column_config.SelectboxColumn(
                "Taux TVA nominal (informatif)", options=["0%", "5.5%", "10%", "20%"]
            ),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_departements = edited_departements_df.dropna(how="all").fillna("").to_dict("records")

with tab_analytique:
    st.markdown(
        "Pour un **compte comptable**, un **point de vente** et un **département LightSpeed** donnés, "
        "la **famille analytique** et le **code analytique** à générer. C'est cette table qui « rejoue » "
        "l'analytique que LightSpeed ne fournit pas — les trois critères sont nécessaires : un même "
        "compte peut porter un code analytique différent selon le département, même sur un seul et "
        "même point de vente (ex. un compte de boisson peut être « Sommellerie » ou « Bar » selon le "
        "département d'origine). Toute combinaison rencontrée à la conversion et absente d'ici bloquera "
        "l'export."
    )
    departements_options = [d["categorie_lightspeed"] for d in edited_departements if d.get("categorie_lightspeed")]
    edited_analytique_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_analytiques", []),
            ["compte", "point_de_vente", "categorie_lightspeed", "famille", "code_analytique", "commentaires"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_analytique",
        column_config={
            "compte": st.column_config.SelectboxColumn("Compte comptable", options=comptes_options, required=True),
            "point_de_vente": st.column_config.SelectboxColumn(
                "Point de vente",
                options=[p["code"] for p in edited_pdv] if edited_pdv else [],
                required=True,
            ),
            "categorie_lightspeed": st.column_config.SelectboxColumn(
                "Département LightSpeed", options=departements_options, required=True
            ),
            "famille": st.column_config.TextColumn("Famille analytique", required=True),
            "code_analytique": st.column_config.TextColumn("Code analytique généré", required=True),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_analytique = edited_analytique_df.dropna(how="all").fillna("").to_dict("records")

with tab_paiement:
    st.markdown(
        "Correspondance entre chaque **mode de paiement LightSpeed** (Carte bleue, Espèces, "
        "Deliveroo, UberEats...) et son **compte de contrepartie** (banque, caisse, créance "
        "plateforme) dans Pennylane. Un mode de paiement non mappé bloque également l'export "
        "(l'écriture serait déséquilibrée)."
    )
    edited_paiement_df = st.data_editor(
        _as_editable_df(mappings.get("comptes_paiement", []), ["mode_paiement", "compte", "libelle_compte", "commentaires"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_paiement",
        column_config={
            "mode_paiement": st.column_config.TextColumn("Mode de paiement LightSpeed", required=True),
            "compte": st.column_config.TextColumn("Compte de contrepartie", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_paiement = edited_paiement_df.dropna(how="all").fillna("").to_dict("records")

with tab_tva:
    st.markdown("Compte de **TVA collectée** à utiliser pour chaque taux de TVA rencontré dans les ventes.")
    edited_tva_df = st.data_editor(
        _as_editable_df(mappings.get("comptes_tva", []), ["taux", "compte", "libelle_compte", "commentaires"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_tva",
        column_config={
            "taux": st.column_config.SelectboxColumn(
                "Taux de TVA", options=["0%", "5.5%", "10%", "20%"], required=True
            ),
            "compte": st.column_config.TextColumn("Compte de TVA collectée", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_tva = edited_tva_df.dropna(how="all").fillna("").to_dict("records")

st.divider()
b1, b2, _ = st.columns([1, 1, 4])
if b1.button("💾 Enregistrer les tables de correspondance", type="primary"):
    save_mappings(
        client_id,
        {
            **mappings,
            "points_de_vente": edited_pdv,
            "comptes_de_vente": edited_comptes,
            "departements": edited_departements,
            "comptes_analytiques": edited_analytique,
            "comptes_paiement": edited_paiement,
            "comptes_tva": edited_tva,
        },
    )
    st.session_state.pop("resultats", None)
    st.success("Tables de correspondance enregistrées.")

if b2.button("🗑️ Vider ce référentiel"):
    reset_to_empty(client_id)
    st.session_state.pop("resultats", None)
    st.rerun()
