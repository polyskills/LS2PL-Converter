"""
Réglages ne relevant ni de la table de correspondance métier (comptes,
points de vente...) ni de la fiche client elle-même : paramètres généraux
de conversion et configuration de la réception automatique des exports par
mail, toujours propres au client sélectionné.
"""
from __future__ import annotations

import json

import streamlit as st

from core.client_store import get_client, set_email_config
from core.mapping_store import load_mappings, save_mappings
from core.timezone import now_local
from core.ui_common import render_infos_techniques, select_client

client_id = select_client()

st.title("⚙️ Réglages")

if client_id is None:
    st.info("Créez un client (page **Clients**) avant de pouvoir régler ses paramètres.")
    st.stop()

mappings = load_mappings(client_id)
client = get_client(client_id)

tab_generaux, tab_email, tab_sauvegarde, tab_infos = st.tabs(
    ["Paramètres généraux", "Gestion Email", "Sauvegarde", "Informations"]
)

with tab_generaux:
    st.subheader("Paramètres généraux de conversion")
    st.caption("Réglages appliqués à toutes les conversions de ce client.")
    params = mappings.get("parametres", {})
    c1, c2 = st.columns(2)
    with c1:
        code_journal = st.text_input("Code journal par défaut", value=params.get("code_journal", "VT"))
        code_pays = st.text_input("Code pays du compte", value=params.get("code_pays", "FR"))
        devise = st.text_input("Devise", value=params.get("devise", "EUR"))
        famille = st.text_input(
            "Famille analytique par défaut (si non précisée ligne par ligne)",
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

    if st.button("💾 Enregistrer les paramètres généraux", type="primary"):
        save_mappings(
            client_id,
            {
                **mappings,
                "parametres": {
                    "code_journal": code_journal,
                    "code_pays": code_pays,
                    "devise": devise,
                    "famille_categorie_analytique": famille,
                    "compte_ecart": compte_ecart,
                    "libelle_compte_ecart": libelle_ecart,
                    "tolerance_equilibrage": tolerance,
                },
            },
        )
        st.success("Paramètres généraux enregistrés.")

with tab_email:
    st.subheader("Réception automatique des exports LightSpeed par mail")
    st.caption(
        "La boîte mail vit dans le tenant M365 du client. Une adresse dédiée par point de vente se "
        "paramètre dans « Table de correspondance » ; ici, uniquement le tenant et la boîte mail à "
        "interroger. Laisser vide désactive le fetch automatique pour ce client. "
        "Voir `deploy/windows/README.md` ou `deploy/macos/README.md` (selon l'OS d'hébergement) pour la mise en "
        "place complète (app Azure AD, consentement admin, service)."
    )
    ce1, ce2 = st.columns(2)
    tenant_id = ce1.text_input(
        "Tenant ID Azure AD du client",
        value=client.get("email_tenant_id", ""),
        help="Identifiant du tenant M365 du client (Entra ID > Vue d'ensemble). "
        "Nécessite le consentement admin du client sur l'app Azure AD Polyskills.",
    )
    mailbox = ce2.text_input(
        "Boîte mail à interroger (UPN)",
        value=client.get("email_mailbox", ""),
        help="Boîte partagée recevant les adresses dédiées (ex. rapport_ls_paris_bar@...).",
    )
    if st.button("💾 Enregistrer la config mail"):
        set_email_config(client_id, tenant_id, mailbox)
        st.success("Config mail enregistrée.")
        st.rerun()

with tab_sauvegarde:
    st.subheader("💾 Sauvegarde du référentiel")
    st.caption(
        "Exportez l'intégralité de la « Table de correspondance » de ce client (points de vente, "
        "comptes, codes analytiques, attribution analytique, moyens de paiement, TVA, paramètres...) "
        "dans un fichier de sauvegarde, et restaurez-la en cas de besoin (erreur de manipulation, "
        "changement à tester, migration...)."
    )

    cs1, cs2 = st.columns(2)

    with cs1:
        st.markdown("**Créer une sauvegarde**")
        horodatage_export = now_local().strftime("%Y-%m-%d %H:%M:%S")
        sauvegarde = {
            "_meta": {
                "client_id": client_id,
                "client_nom": client["nom"],
                "exporte_le": horodatage_export,
            },
            "mappings": mappings,
        }
        contenu_json = json.dumps(sauvegarde, ensure_ascii=False, indent=2)
        nom_fichier = f"referentiel_{client_id}_{now_local().strftime('%Y%m%d_%H%M%S')}.json"
        st.download_button(
            "⬇️ Télécharger la sauvegarde (.json)",
            data=contenu_json,
            file_name=nom_fichier,
            mime="application/json",
            use_container_width=True,
        )

    with cs2:
        st.markdown("**Restaurer une sauvegarde**")
        fichier_restauration = st.file_uploader(
            "Fichier de sauvegarde (.json)",
            type=["json"],
            key="uploader_restauration_referentiel",
        )

        if fichier_restauration is not None:
            try:
                contenu = json.loads(fichier_restauration.getvalue().decode("utf-8"))
            except Exception:
                st.error("❌ Fichier illisible : ce n'est pas un fichier JSON valide.")
                contenu = None

            if contenu is not None:
                mappings_a_restaurer = contenu.get("mappings")
                meta = contenu.get("_meta", {})
                if not isinstance(mappings_a_restaurer, dict):
                    st.error("❌ Fichier invalide : il ne s'agit pas d'une sauvegarde de référentiel reconnue.")
                else:
                    if meta.get("client_id") and meta.get("client_id") != client_id:
                        st.warning(
                            f"⚠️ Cette sauvegarde provient d'un autre client "
                            f"(« {meta.get('client_nom', meta.get('client_id'))} »). "
                            f"La restaurer remplacera quand même le référentiel de « {client['nom']} »."
                        )

                    st.caption(
                        f"Sauvegarde exportée le {meta.get('exporte_le', '?')}" +
                        (f" pour « {meta['client_nom']} »" if meta.get("client_nom") else "") + "."
                    )
                    recap = {
                        "Points de vente": len(mappings_a_restaurer.get("points_de_vente", [])),
                        "Comptes de vente": len(mappings_a_restaurer.get("comptes_de_vente", [])),
                        "Départements": len(mappings_a_restaurer.get("departements", [])),
                        "Codes analytiques": len(mappings_a_restaurer.get("codes_analytiques", [])),
                        "Attribution analytique": len(mappings_a_restaurer.get("comptes_analytiques", [])),
                        "Moyens de paiement": len(mappings_a_restaurer.get("comptes_paiement", [])),
                        "Moyens de paiement ignorés": len(mappings_a_restaurer.get("modes_paiement_ignores", [])),
                        "Taux de TVA": len(mappings_a_restaurer.get("comptes_tva", [])),
                    }
                    st.table(recap)

                    st.warning(
                        f"⚠️ La restauration **écrasera définitivement** le référentiel actuel de « {client['nom']} » "
                        "avec le contenu de cette sauvegarde. Cette action est irréversible."
                    )
                    if st.button("✅ Confirmer la restauration", type="primary"):
                        save_mappings(client_id, mappings_a_restaurer)
                        st.success("Référentiel restauré avec succès.")
                        st.rerun()

with tab_infos:
    st.subheader("🔧 Informations techniques")
    st.caption(
        "Anciennement dans le menu latéral de chaque page ; rassemblé ici pour désencombrer la navigation."
    )
    render_infos_techniques(client_id)
