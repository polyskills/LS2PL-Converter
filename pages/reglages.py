"""
Réglages ne relevant ni de la table de correspondance métier (comptes,
points de vente...) ni de la fiche client elle-même : paramètres généraux
de conversion et configuration de la réception automatique des exports par
mail, toujours propres au client sélectionné.
"""
from __future__ import annotations

import json

import streamlit as st

from core.app_config import get_footer_sidebar, set_footer_sidebar
from core.client_store import get_client, rename_client, set_email_config
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
        st.session_state["_config_mail_enregistree"] = True
        st.rerun()
    if st.session_state.pop("_config_mail_enregistree", None):
        st.success("✅ Config mail enregistrée.")

with tab_sauvegarde:
    st.subheader("💾 Sauvegarde du référentiel et des réglages")
    st.caption(
        "Exportez l'intégralité de l'environnement de travail de ce client — « Table de correspondance » "
        "(points de vente, comptes, codes analytiques, attribution analytique, moyens de paiement, TVA...), "
        "paramètres généraux de conversion (code journal, compte d'écart...) et configuration de la réception "
        "mail (tenant, boîte à interroger) — dans un fichier de sauvegarde, et restaurez-le en cas de besoin "
        "(erreur de manipulation, changement à tester, migration...) sans risquer un réglage resté différent."
    )

    # Confirmation affichée au rendu SUIVANT la restauration (posée en session_state juste
    # avant le st.rerun() du bouton de confirmation, plus bas) : un st.success() suivi
    # immédiatement d'un st.rerun() disparaît avant que quiconque ait pu le voir.
    if st.session_state.pop("_restauration_reussie", None):
        st.success("✅ Référentiel et réglages restaurés avec succès.")

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
            # Paramètres généraux de conversion (code journal, compte d'écart...) sont
            # déjà dans mappings["parametres"], donc déjà couverts ci-dessus. Seule la
            # config mail (tenant, boîte) vit ailleurs, sur la fiche client elle-même
            # (core.client_store), pas dans le référentiel : sans ce bloc, une
            # restauration laisserait ce réglage-là inchangé, contrairement à
            # l'intention "environnement de travail complet".
            "reglages_client": {
                "email_tenant_id": client.get("email_tenant_id", ""),
                "email_mailbox": client.get("email_mailbox", ""),
            },
        }
        contenu_json = json.dumps(sauvegarde, ensure_ascii=False, indent=2)
        nom_fichier = f"sauvegarde_{client_id}_{now_local().strftime('%Y%m%d_%H%M%S')}.json"
        st.download_button(
            "⬇️ Télécharger la sauvegarde (.json)",
            data=contenu_json,
            file_name=nom_fichier,
            mime="application/json",
            use_container_width=True,
        )

    with cs2:
        st.markdown("**Restaurer une sauvegarde**")
        # Clé variable (compteur en session_state, jamais réassigné directement à la
        # main du widget - interdit par Streamlit) : after une restauration réussie,
        # on l'incrémente pour forcer un uploader vierge plutôt que de laisser le
        # fichier déjà traité, son récapitulatif et son bouton de confirmation
        # trainer à l'écran comme s'il restait à cliquer.
        _version_uploader = st.session_state.get("_version_uploader_restauration", 0)
        fichier_restauration = st.file_uploader(
            "Fichier de sauvegarde (.json)",
            type=["json"],
            key=f"uploader_restauration_referentiel_{_version_uploader}",
        )

        if fichier_restauration is not None:
            try:
                contenu = json.loads(fichier_restauration.getvalue().decode("utf-8"))
            except Exception:
                st.error("❌ Fichier illisible : ce n'est pas un fichier JSON valide.")
                contenu = None

            if contenu is not None:
                mappings_a_restaurer = contenu.get("mappings")
                reglages_client_a_restaurer = contenu.get("reglages_client")
                meta = contenu.get("_meta", {})
                if not isinstance(mappings_a_restaurer, dict):
                    st.error("❌ Fichier invalide : il ne s'agit pas d'une sauvegarde de référentiel reconnue.")
                else:
                    if meta.get("client_id") and meta.get("client_id") != client_id:
                        st.warning(
                            f"⚠️ Cette sauvegarde provient d'un autre client "
                            f"(« {meta.get('client_nom', meta.get('client_id'))} »). "
                            f"La restaurer remplacera quand même le référentiel et les réglages de « {client['nom']} »."
                        )

                    st.caption(
                        f"Sauvegarde exportée le {meta.get('exporte_le', '?')}" +
                        (f" pour « {meta['client_nom']} »" if meta.get("client_nom") else "") + "."
                    )
                    nom_a_restaurer = meta.get("client_nom", "").strip()
                    renommage_prevu = bool(nom_a_restaurer) and nom_a_restaurer != client["nom"]
                    recap = {
                        "Points de vente": len(mappings_a_restaurer.get("points_de_vente", [])),
                        "Comptes de vente": len(mappings_a_restaurer.get("comptes_de_vente", [])),
                        "Départements": len(mappings_a_restaurer.get("departements", [])),
                        "Codes analytiques": len(mappings_a_restaurer.get("codes_analytiques", [])),
                        "Attribution analytique": len(mappings_a_restaurer.get("comptes_analytiques", [])),
                        "Moyens de paiement": len(mappings_a_restaurer.get("comptes_paiement", [])),
                        "Moyens de paiement ignorés": len(mappings_a_restaurer.get("modes_paiement_ignores", [])),
                        "Taux de TVA": len(mappings_a_restaurer.get("comptes_tva", [])),
                        "Paramètres généraux": "inclus (code journal, compte d'écart...)",
                        "Config mail (tenant/boîte)": (
                            "incluse" if isinstance(reglages_client_a_restaurer, dict)
                            else "non incluse (sauvegarde d'une version antérieure) — laissée telle quelle"
                        ),
                        "Nom du client": (
                            f"« {client['nom']} » → « {nom_a_restaurer} »" if renommage_prevu
                            else f"inchangé (« {client['nom']} »)"
                        ),
                    }
                    st.table(recap)

                    st.warning(
                        f"⚠️ La restauration **écrasera définitivement** le référentiel et les réglages actuels de "
                        f"« {client['nom']} » avec le contenu de cette sauvegarde. Cette action est irréversible."
                    )
                    if st.button("✅ Confirmer la restauration", type="primary"):
                        save_mappings(client_id, mappings_a_restaurer)
                        if isinstance(reglages_client_a_restaurer, dict):
                            set_email_config(
                                client_id,
                                reglages_client_a_restaurer.get("email_tenant_id", ""),
                                reglages_client_a_restaurer.get("email_mailbox", ""),
                            )
                        if renommage_prevu:
                            rename_client(client_id, nom_a_restaurer)
                        st.session_state["_restauration_reussie"] = True
                        st.session_state["_version_uploader_restauration"] = _version_uploader + 1
                        st.rerun()

with tab_infos:
    st.subheader("🔧 Informations techniques")
    st.caption(
        "Anciennement dans le menu latéral de chaque page ; rassemblé ici pour désencombrer la navigation."
    )
    render_infos_techniques(client_id)

    st.divider()
    st.subheader("🖋️ Pied de page du menu latéral")
    st.caption(
        "Texte affiché tout en bas du menu de navigation, sur toutes les pages et pour tous les "
        "clients (réglage global, pas propre à ce client)."
    )
    footer_actuel = get_footer_sidebar()
    nouveau_footer = st.text_input("Texte du pied de page", value=footer_actuel)
    if st.button("💾 Enregistrer le pied de page"):
        set_footer_sidebar(nouveau_footer)
        st.session_state["_footer_enregistre"] = True
        st.rerun()
    if st.session_state.pop("_footer_enregistre", None):
        st.success("✅ Pied de page enregistré.")
