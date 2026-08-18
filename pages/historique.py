"""
Historique des conversions du client sélectionné : fichiers source et générés
conservés (les MAX_HISTORIQUE_CONVERSIONS plus récentes seulement, cf.
core.history_store), indicateurs de contrôle par conversion, et alerte
(informative, non bloquante) sur l'ancienneté de la dernière conversion
réussie.
"""
from __future__ import annotations

import os

import streamlit as st

from core.history_store import (
    MAX_HISTORIQUE_CONVERSIONS,
    echecs_apres_derniere_reussite,
    jours_depuis_derniere_conversion_reussie,
    list_history,
)
from core.ui_common import select_client

client_id = select_client()

st.title("🕓 Historique des conversions")
st.caption(
    f"Les {MAX_HISTORIQUE_CONVERSIONS} conversions les plus récentes sont conservées ici avec leur fichier "
    "source, leur fichier généré, et le détail des contrôles effectués — pour l'audit et l'explication "
    "d'éventuelles anomalies. Les conversions plus anciennes restent consultables ailleurs (Pennylane, "
    "export comptable du client)."
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
st.subheader("⚠️ État du fetch automatique")

echecs_recents = echecs_apres_derniere_reussite(entries)
if echecs_recents:
    plus_recent = echecs_recents[0]
    st.error(
        f"❌ {len(echecs_recents)} tentative(s) en échec depuis la dernière conversion réussie — "
        f"la plus récente : {plus_recent['horodatage']} ({plus_recent['point_de_vente']}). "
        "Voir le détail dans la liste ci-dessous."
    )

jours = jours_depuis_derniere_conversion_reussie(entries)
if jours is None:
    st.warning(
        "Aucune conversion réussie (statut OK) dans l'historique conservé. Vérifier que le fetch "
        "automatique fonctionne toujours, ou que la fermeture prolongée est bien volontaire."
    )
elif jours == 0:
    st.success("Dernière conversion réussie : aujourd'hui.")
elif jours == 1:
    st.info("Dernière conversion réussie : hier.")
else:
    (st.warning if jours >= 3 else st.info)(f"Dernière conversion réussie il y a {jours} jours.")

st.divider()
st.subheader(f"Conversions ({len(filtered)}/{len(entries)})")

statut_icone = {"OK": "✅", "AVERTISSEMENT": "⚠️", "ERREUR": "❌"}

for e in filtered:
    titre = (
        f"{statut_icone.get(e['statut'], '•')} {e['horodatage']} — {e['point_de_vente']} — "
        f"{e['fichier_source_nom']} (pièce {e.get('numero_piece') or '—'})"
    )
    with st.expander(titre):
        destinataires = e.get("destinataires_email") or []
        st.caption(
            "📧 Destinataire(s) mail : " + (", ".join(destinataires) if destinataires else "— (import manuel)")
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("CA HT source (LightSpeed)", f"{e['ca_ht_source']:,.2f} €".replace(",", " "))
        m2.metric(
            "CA HT généré (Pennylane)",
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
