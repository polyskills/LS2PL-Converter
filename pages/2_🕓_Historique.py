"""
Historique des conversions du client sélectionné : fichiers source et générés
conservés, indicateurs de contrôle par conversion, et détection (informative,
non bloquante) des jours sans import pour un point de vente donné.
"""
from __future__ import annotations

import os

import streamlit as st

from core.history_store import detect_missing_days, list_history
from core.ui_common import select_client

st.set_page_config(page_title="Historique", page_icon="🕓", layout="wide")

client_id = select_client()

st.title("🕓 Historique des conversions")
st.caption(
    "Chaque conversion réalisée est conservée ici avec son fichier source, son fichier généré, "
    "et le détail des contrôles effectués — pour l'audit et l'explication d'éventuelles anomalies."
)

if client_id is None:
    st.stop()

entries = list_history(client_id)

if not entries:
    st.info("Aucune conversion enregistrée pour ce client pour l'instant.")
    st.stop()

pdv_options = sorted({e["point_de_vente"] for e in entries})
c1, c2 = st.columns([2, 2])
filtre_pdv = c1.multiselect("Filtrer par point de vente", options=pdv_options, default=pdv_options)
filtre_statut = c2.multiselect(
    "Filtrer par statut", options=["OK", "AVERTISSEMENT", "ERREUR"], default=["OK", "AVERTISSEMENT", "ERREUR"]
)

filtered = [e for e in entries if e["point_de_vente"] in filtre_pdv and e["statut"] in filtre_statut]

st.divider()
st.subheader("⚠️ Jours sans conversion enregistrée")
trous = detect_missing_days(entries)
if trous:
    st.warning(
        f"{len(trous)} jour(s) sans conversion enregistrée entre la première et la dernière date "
        "connue, pour au moins un point de vente. Ceci est purement informatif — un point de vente "
        "peut être légitimement fermé un jour donné — mais mérite vérification."
    )
    st.dataframe(sorted(trous, key=lambda t: (t["point_de_vente"], t["date_manquante"])), use_container_width=True, hide_index=True)
else:
    st.success("Aucun trou détecté dans le suivi des dates connues.")

st.divider()
st.subheader(f"Conversions ({len(filtered)}/{len(entries)})")

statut_icone = {"OK": "✅", "AVERTISSEMENT": "⚠️", "ERREUR": "❌"}

for e in filtered:
    titre = (
        f"{statut_icone.get(e['statut'], '•')} {e['horodatage']} — {e['point_de_vente']} — "
        f"{e['fichier_source_nom']} (pièce {e.get('numero_piece') or '—'})"
    )
    with st.expander(titre):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("CA HT source", f"{e['ca_ht_source']:,.2f} €".replace(",", " "))
        m2.metric(
            "CA HT généré",
            f"{e['ca_ht_genere']:,.2f} €".replace(",", " "),
            delta=f"{e['ca_ht_genere'] - e['ca_ht_source']:+.2f} €",
            delta_color="off" if abs(e["ca_ht_genere"] - e["ca_ht_source"]) < 0.01 else "inverse",
        )
        m3.metric("Total Débit", f"{e['total_debit']:,.2f} €".replace(",", " "))
        m4.metric(
            "Total Crédit",
            f"{e['total_credit']:,.2f} €".replace(",", " "),
            delta="Équilibré" if abs(e["total_debit"] - e["total_credit"]) < 0.01 else "Déséquilibré",
            delta_color="off" if abs(e["total_debit"] - e["total_credit"]) < 0.01 else "inverse",
        )

        for err in e.get("erreurs", []):
            st.error(err)
        for a in e.get("avertissements", []):
            st.warning(a)
        if not e.get("erreurs") and not e.get("avertissements"):
            st.success("Aucune anomalie relevée sur cette conversion.")

        dl1, dl2 = st.columns(2)
        src_path = e.get("fichier_source_chemin")
        if src_path and os.path.exists(src_path):
            with open(src_path, "rb") as f:
                dl1.download_button(
                    "⬇️ Fichier source LightSpeed",
                    data=f.read(),
                    file_name=e["fichier_source_nom"],
                    key=f"src_{e['id']}",
                )
        gen_path = e.get("fichier_genere_chemin")
        if gen_path and os.path.exists(gen_path):
            with open(gen_path, "rb") as f:
                dl2.download_button(
                    "⬇️ Fichier Pennylane généré (.csv)",
                    data=f.read(),
                    file_name=os.path.basename(gen_path),
                    key=f"gen_{e['id']}",
                )
