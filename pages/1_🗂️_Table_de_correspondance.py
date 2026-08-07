"""
Page de paramétrage des tables de correspondance utilisées par la moulinette
de conversion LightSpeed → Pennylane.

Toutes les tables sont éditables directement (ajout/suppression de lignes) et
persistées dans data/mappings.json.
"""
from __future__ import annotations

import streamlit as st

from core.mapping_store import DEFAULT_MAPPINGS, load_mappings, save_mappings

st.set_page_config(page_title="Table de correspondance", page_icon="🗂️", layout="wide")

st.title("🗂️ Table de correspondance")
st.caption(
    "LightSpeed ne gère pas de code analytique : c'est la combinaison "
    "**compte comptable × point de vente** qui permet de le reconstituer. "
    "Paramétrez ici les quatre tables utilisées par la conversion."
)

mappings = load_mappings()

tab_pdv, tab_ventes, tab_analytique, tab_paiement, tab_tva, tab_param = st.tabs(
    [
        "Points de vente",
        "Comptes de vente",
        "Codes analytiques",
        "Contreparties de paiement",
        "TVA collectée",
        "Paramètres généraux",
    ]
)

with tab_pdv:
    st.markdown("Liste des points de vente (sites, salles, activités...) rencontrés dans les exports LightSpeed.")
    edited_pdv = st.data_editor(
        mappings.get("points_de_vente", []),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_pdv",
        column_config={
            "code": st.column_config.TextColumn("Code point de vente", required=True),
            "libelle": st.column_config.TextColumn("Libellé", required=True),
        },
    )

with tab_ventes:
    st.markdown(
        "Correspondance entre chaque **catégorie / référence comptable LightSpeed** "
        "(colonne « Références comptables » de l'export) et le **compte général de vente Pennylane**."
    )
    edited_ventes = st.data_editor(
        mappings.get("comptes_ventes", []),
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

with tab_analytique:
    st.markdown(
        "Pour un **compte comptable** donné et un **point de vente** donné, le **code analytique** à générer. "
        "C'est cette table qui « rejoue » l'analytique que LightSpeed ne fournit pas."
    )
    edited_analytique = st.data_editor(
        mappings.get("comptes_analytiques", []),
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
            "code_analytique": st.column_config.TextColumn("Code analytique généré", required=True),
        },
    )

with tab_paiement:
    st.markdown(
        "Correspondance entre chaque **mode de paiement LightSpeed** (Carte bleue, Espèces, Chèque...) "
        "et son **compte de contrepartie** (banque, caisse) dans Pennylane."
    )
    edited_paiement = st.data_editor(
        mappings.get("comptes_paiement", []),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_paiement",
        column_config={
            "mode_paiement": st.column_config.TextColumn("Mode de paiement LightSpeed", required=True),
            "compte": st.column_config.TextColumn("Compte de contrepartie", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
        },
    )

with tab_tva:
    st.markdown("Compte de **TVA collectée** à utiliser pour chaque taux de TVA rencontré dans les ventes.")
    edited_tva = st.data_editor(
        mappings.get("comptes_tva", []),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_tva",
        column_config={
            "taux": st.column_config.SelectboxColumn("Taux de TVA", options=["0%", "5.5%", "10%", "20%"], required=True),
            "compte": st.column_config.TextColumn("Compte de TVA collectée", required=True),
            "libelle_compte": st.column_config.TextColumn("Libellé du compte"),
        },
    )

with tab_param:
    st.markdown("Réglages généraux appliqués à toutes les conversions.")
    params = mappings.get("parametres", {})
    c1, c2 = st.columns(2)
    with c1:
        code_journal = st.text_input("Code journal par défaut", value=params.get("code_journal", "VT"))
        code_pays = st.text_input("Code pays du compte", value=params.get("code_pays", "FR"))
        devise = st.text_input("Devise", value=params.get("devise", "EUR"))
        famille = st.text_input(
            "Famille de catégories analytique",
            value=params.get("famille_categorie_analytique", "POINT_DE_VENTE"),
        )
    with c2:
        compte_ecart = st.text_input("Compte d'écart / report (équilibrage)", value=params.get("compte_ecart", "471000"))
        libelle_ecart = st.text_input(
            "Libellé du compte d'écart", value=params.get("libelle_compte_ecart", "Compte d'attente - écart de report LightSpeed")
        )
        tolerance = st.number_input(
            "Tolérance de rapprochement du report (€)",
            value=float(params.get("tolerance_equilibrage", 0.02)),
            step=0.01,
            format="%.2f",
        )
    edited_params = {
        "code_journal": code_journal,
        "code_pays": code_pays,
        "devise": devise,
        "famille_categorie_analytique": famille,
        "compte_ecart": compte_ecart,
        "libelle_compte_ecart": libelle_ecart,
        "tolerance_equilibrage": tolerance,
    }

st.divider()
b1, b2, _ = st.columns([1, 1, 4])
if b1.button("💾 Enregistrer les tables de correspondance", type="primary"):
    save_mappings(
        {
            "parametres": edited_params,
            "points_de_vente": edited_pdv,
            "comptes_ventes": edited_ventes,
            "comptes_analytiques": edited_analytique,
            "comptes_paiement": edited_paiement,
            "comptes_tva": edited_tva,
        }
    )
    st.session_state.pop("resultats", None)
    st.success("Tables de correspondance enregistrées.")

if b2.button("↩️ Réinitialiser les valeurs d'exemple"):
    save_mappings(DEFAULT_MAPPINGS)
    st.session_state.pop("resultats", None)
    st.rerun()
