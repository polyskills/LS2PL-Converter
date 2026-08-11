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
    donc toujours un DataFrame avec les colonnes attendues, même à 0 ligne."""
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)[columns]

client_id = select_client()

st.title("🗂️ Table de correspondance")
st.caption(
    "LightSpeed ne gère pas de code analytique : c'est la combinaison "
    "**compte comptable × point de vente** qui permet de le reconstituer. "
    "Paramétrez ici les tables utilisées par la conversion, propres au client sélectionné. "
    "Les réglages généraux (code journal, compte d'écart...) se trouvent page **Réglages**."
)

if client_id is None:
    st.stop()

mappings = load_mappings(client_id)

tab_pdv, tab_ventes, tab_analytique, tab_paiement, tab_tva = st.tabs(
    [
        "Points de vente",
        "Comptes de vente",
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
        _as_editable_df(mappings.get("points_de_vente", []), ["code", "libelle", "adresse_email"]),
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
        },
    )
    edited_pdv = edited_pdv_df.dropna(how="all").fillna("").to_dict("records")

with tab_ventes:
    st.markdown(
        "Correspondance entre chaque **catégorie / référence comptable LightSpeed** "
        "(colonne « Références comptables » de l'export) et le **compte général de vente Pennylane**. "
        "Toute catégorie rencontrée dans un fichier importé et absente d'ici bloquera l'export."
    )
    edited_ventes_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_ventes", []),
            ["categorie_lightspeed", "compte", "libelle_compte", "taux_tva"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_ventes",
        column_config={
            "categorie_lightspeed": st.column_config.TextColumn("Catégorie LightSpeed", required=True),
            "compte": st.column_config.TextColumn("Compte Pennylane", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
            "taux_tva": st.column_config.SelectboxColumn("Taux TVA nominal", options=["0%", "5.5%", "10%", "20%"]),
        },
    )
    edited_ventes = edited_ventes_df.dropna(how="all").fillna("").to_dict("records")

with tab_analytique:
    st.markdown(
        "Pour un **compte comptable** donné et un **point de vente** donné, la **famille analytique** "
        "et le **code analytique** à générer. C'est cette table qui « rejoue » l'analytique que "
        "LightSpeed ne fournit pas. Toute combinaison (compte, point de vente) rencontrée à la "
        "conversion et absente d'ici bloquera l'export."
    )
    edited_analytique_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_analytiques", []),
            ["compte", "point_de_vente", "famille", "code_analytique"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_analytique",
        column_config={
            "compte": st.column_config.TextColumn("Compte comptable", required=True),
            "point_de_vente": st.column_config.SelectboxColumn(
                "Point de vente",
                options=[p["code"] for p in edited_pdv] if edited_pdv else [],
                required=True,
            ),
            "famille": st.column_config.TextColumn("Famille analytique", required=True),
            "code_analytique": st.column_config.TextColumn("Code analytique généré", required=True),
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
        _as_editable_df(mappings.get("comptes_paiement", []), ["mode_paiement", "compte", "libelle_compte"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_paiement",
        column_config={
            "mode_paiement": st.column_config.TextColumn("Mode de paiement LightSpeed", required=True),
            "compte": st.column_config.TextColumn("Compte de contrepartie", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
        },
    )
    edited_paiement = edited_paiement_df.dropna(how="all").fillna("").to_dict("records")

with tab_tva:
    st.markdown("Compte de **TVA collectée** à utiliser pour chaque taux de TVA rencontré dans les ventes.")
    edited_tva_df = st.data_editor(
        _as_editable_df(mappings.get("comptes_tva", []), ["taux", "compte", "libelle_compte"]),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_tva",
        column_config={
            "taux": st.column_config.SelectboxColumn(
                "Taux de TVA", options=["0%", "5.5%", "10%", "20%"], required=True
            ),
            "compte": st.column_config.TextColumn("Compte de TVA collectée", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
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
            "comptes_ventes": edited_ventes,
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
