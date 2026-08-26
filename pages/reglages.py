"""
Réglages ne relevant ni de la table de correspondance métier (comptes,
points de vente...) ni de la fiche client elle-même : paramètres généraux
de conversion et configuration de la réception automatique des exports par
mail, toujours propres au client sélectionné.
"""
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

from core.app_config import get_footer_sidebar, get_url_app, set_footer_sidebar, set_url_app
from core.client_store import (
    DEFAULT_PREFIXE_MAIL,
    get_client,
    rename_client,
    set_azure_credentials,
    set_email_config,
    set_prefixe_mail,
)
from core.mapping_store import build_export_global_xlsx, load_mappings, save_mappings
from core.self_update import appliquer_mise_a_jour, redemarrer_apres_delai, verifier_mise_a_jour
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
        "paramètre dans « Table de correspondance » ; ici, le tenant, la boîte mail à interroger, et "
        "l'app Azure AD créée dans ce tenant. Laisser le tenant/la boîte vides désactive le fetch "
        "automatique pour ce client. Voir `docs/configuration_m365_client.md` pour la mise en place "
        "complète côté client (création de l'app, consentement admin), et `deploy/windows/README.md` "
        "ou `deploy/macos/README.md` pour le service d'hébergement."
    )
    ce1, ce2 = st.columns(2)
    tenant_id = ce1.text_input(
        "Tenant ID Azure AD du client",
        value=client.get("email_tenant_id", ""),
        help="Identifiant du tenant M365 du client (Entra ID > Vue d'ensemble).",
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

    st.divider()
    st.markdown("**Préfixe des mails du fetch automatique**")
    st.caption(
        "Préfixe entre crochets utilisé dans le sujet des mails envoyés à ce client (résultat de "
        "conversion, notifications d'échec) — ex. « ASPP » donne des sujets du type « [ASPP] "
        f"Conversion LS2PL — ... ». Laisser vide pour reprendre la valeur par défaut (« {DEFAULT_PREFIXE_MAIL} »)."
    )
    prefixe_mail = st.text_input("Préfixe des mails", value=client.get("prefixe_mail", ""))
    if st.button("💾 Enregistrer le préfixe des mails"):
        set_prefixe_mail(client_id, prefixe_mail)
        st.session_state["_prefixe_mail_enregistre"] = True
        st.rerun()
    if st.session_state.pop("_prefixe_mail_enregistre", None):
        st.success("✅ Préfixe des mails enregistré.")

    st.divider()
    st.markdown("**App Azure AD de ce client**")
    st.caption(
        "ID d'application et secret client de l'app Azure AD créée dans le tenant de ce client "
        "(étape 0 de `docs/configuration_m365_client.md`), nécessaires pour que le fetch automatique "
        "(service `email_poller.py` ou bouton « Relever les mails maintenant » page Convertisseur) "
        "obtienne un jeton Microsoft Graph. Laisser vide pour retomber sur les variables "
        "d'environnement globales du serveur (`LSPENNYLANE_AZURE_CLIENT_ID`/`_SECRET`, historique — "
        "ne fonctionne que pour un seul client à la fois). ⚠️ Enregistrés **en clair** sur le disque, "
        "comme le reste du référentiel : quiconque a accès au serveur peut les lire."
    )
    ca1, ca2 = st.columns(2)
    azure_client_id = ca1.text_input("ID d'application (Client ID)", value=client.get("azure_client_id", ""))
    azure_client_secret = ca2.text_input(
        "Secret client (Client Secret)", value=client.get("azure_client_secret", ""), type="password"
    )
    if st.button("💾 Enregistrer les identifiants Azure"):
        set_azure_credentials(client_id, azure_client_id, azure_client_secret)
        st.session_state["_identifiants_azure_enregistres"] = True
        st.rerun()
    if st.session_state.pop("_identifiants_azure_enregistres", None):
        st.success("✅ Identifiants Azure enregistrés.")

with tab_sauvegarde:
    st.subheader("💾 Sauvegarde du référentiel et des réglages")
    st.caption(
        "Exportez l'intégralité de l'environnement de travail de ce client — « Table de correspondance » "
        "(points de vente, comptes, codes analytiques, attribution analytique, moyens de paiement, TVA...), "
        "paramètres généraux de conversion (code journal, compte d'écart...) et configuration de la réception "
        "mail (tenant, boîte à interroger, identifiants Azure) — dans un fichier de sauvegarde, et "
        "restaurez-le en cas de besoin (erreur de manipulation, changement à tester, migration...) sans "
        "risquer un réglage resté différent. ⚠️ Ce fichier contient le **secret client Azure AD** en "
        "clair s'il est renseigné : à traiter comme une donnée sensible (ne pas partager, stocker en "
        "lieu sûr)."
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
                "azure_client_id": client.get("azure_client_id", ""),
                "azure_client_secret": client.get("azure_client_secret", ""),
                "prefixe_mail": client.get("prefixe_mail", ""),
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

        st.caption(
            "Ce fichier .json sert à la restauration ci-contre — pour une simple lecture (tableur, "
            "envoi à un tiers), l'export ci-dessous est plus adapté."
        )
        st.download_button(
            "⬇️ Exporter la Table de correspondance (.xlsx, tous les onglets)",
            data=build_export_global_xlsx(mappings),
            file_name=f"table_correspondance_{client_id}_complet_{now_local().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
                        "Comptes de pourboires": len(mappings_a_restaurer.get("comptes_pourboires", [])),
                        "Moyens de paiement ignorés": len(mappings_a_restaurer.get("modes_paiement_ignores", [])),
                        "Taux de TVA": len(mappings_a_restaurer.get("comptes_tva", [])),
                        "Paramètres généraux": "inclus (code journal, compte d'écart...)",
                        "Config mail (tenant/boîte/identifiants Azure)": (
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
                            set_azure_credentials(
                                client_id,
                                reglages_client_a_restaurer.get("azure_client_id", ""),
                                reglages_client_a_restaurer.get("azure_client_secret", ""),
                            )
                            set_prefixe_mail(client_id, reglages_client_a_restaurer.get("prefixe_mail", ""))
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
    st.subheader("🔄 Mise à jour de l'application")
    st.caption(
        "Récupère et installe la dernière version publiée sur la branche suivie, sans passer par un "
        "accès terminal/admin — utile pour appliquer un correctif urgent sans attendre. Redémarre "
        "l'application **et** le service de fetch mail."
    )
    if st.button("🔍 Vérifier les mises à jour"):
        st.session_state["_maj_verification"] = verifier_mise_a_jour()
        st.session_state.pop("_maj_confirmation", None)

    verif = st.session_state.get("_maj_verification")
    if verif:
        if verif["erreur"]:
            st.error(f"❌ Vérification impossible : {verif['erreur']}")
        elif verif["a_jour"]:
            st.success(f"✅ Application à jour (commit `{verif['commit_local']}`, branche `{verif['branche']}`).")
        else:
            st.info(
                f"⬆️ Nouvelle version disponible sur `{verif['branche']}` : `{verif['commit_local']}` → "
                f"`{verif['commit_distant']}`\n\n> {verif['message_distant']}"
            )
            if st.button("⚠️ Installer la mise à jour et redémarrer"):
                st.session_state["_maj_confirmation"] = True

    if st.session_state.get("_maj_confirmation"):
        st.warning(
            "⚠️ L'application et le service de fetch mail vont redémarrer dans quelques secondes — "
            "coupure de quelques secondes pour tous les utilisateurs, et toute saisie en cours non "
            "enregistrée (ex. modifications d'un tableau sans avoir cliqué « Enregistrer ») sera "
            "perdue. Confirmer ?"
        )
        cm1, cm2, _ = st.columns([1, 1, 4])
        if cm1.button("✅ Oui, mettre à jour maintenant", type="primary"):
            resultat_maj = appliquer_mise_a_jour()
            if resultat_maj["succes"]:
                st.session_state.pop("_maj_confirmation", None)
                st.session_state.pop("_maj_verification", None)
                # Sans rerun ici, les deux boutons de confirmation (déjà dessinés plus haut dans
                # ce même passage de script) resteraient affichés sous le message de succès -
                # trompeur, on dirait la mise à jour non prise en compte. redemarrer_apres_delai()
                # est appelé AVANT le rerun : il programme juste un minuteur en tâche de fond, le
                # rerun qui suit ne l'annule pas.
                st.session_state["_maj_resultat"] = resultat_maj
                redemarrer_apres_delai()
                st.rerun()
            else:
                st.error(f"❌ Échec de la mise à jour : {resultat_maj['erreur']}")
        if cm2.button("Annuler la mise à jour"):
            st.session_state.pop("_maj_confirmation", None)
            st.rerun()

    resultat_maj_affiche = st.session_state.get("_maj_resultat")
    if resultat_maj_affiche:
        st.success(
            f"✅ Mise à jour appliquée (commit `{resultat_maj_affiche['nouveau_commit']}`)"
            + (" — dépendances réinstallées." if resultat_maj_affiche["dependances_reinstallees"] else ".")
            + " Redémarrage en cours — vous allez être redirigé automatiquement dès que "
            "l'application est de nouveau disponible."
        )
        # Naviguer vers une autre page pendant le redémarrage affiche un écran cassé : les pages
        # Streamlit changent d'écran SANS recharger le navigateur (même connexion WebSocket
        # réutilisée), or celle-ci est coupée par le redémarrage du process - contrairement à un
        # vrai rechargement de page (F5, ou retour sur /), qui rouvre une connexion fraîche et
        # fonctionne toujours. Plutôt que de compter sur l'utilisateur pour deviner qu'il faut
        # recharger manuellement (confusion : "le site ne fonctionne plus" alors que ce n'est
        # qu'un souci de reconnexion côté navigateur), on sonde nous-mêmes la disponibilité du
        # serveur et on redirige automatiquement vers la racine du site.
        #
        # Deux pièges corrigés après un premier essai qui ne redirigeait jamais, vérifiés en
        # rejouant un vrai cycle arrêt/redémarrage de serveur local :
        # 1. Navigation bloquée par le sandbox : l'iframe de components.html n'a PAS le flag
        #    "allow-top-navigation" (confirmé via la console du navigateur), donc assigner
        #    directement window.parent.location.href DEPUIS CETTE IFRAME est silencieusement
        #    ignoré par le navigateur, sans erreur visible à l'écran. Contournement : injecter un
        #    VRAI <script> (document.createElement, jamais innerHTML - qui n'exécute aucun script)
        #    dans le document PARENT, hors du sandbox ; une fois exécuté LÀ, changer
        #    window.location.href est autorisé normalement.
        # 2. Redirection prématurée : sonder un serveur qui répond encore 200 (l'ancien process,
        #    pas encore sorti) et rediriger dès le premier succès ne prouve rien - il faut
        #    d'abord OBSERVER une coupure confirmée (requête en échec) avant de considérer qu'un
        #    200 qui suit signale un vrai redémarrage, plutôt qu'une simple estimation de délai.
        components.html(
            r"""
            <script>
            const s = window.parent.document.createElement('script');
            s.textContent = `
                (function() {
                    var vuIndisponible = false;
                    function sonder() {
                        fetch(window.location.origin + "/_stcore/health", {cache: "no-store"})
                            .then(function(r) {
                                if (r.ok) {
                                    if (vuIndisponible) { window.location.href = window.location.origin; }
                                    else { setTimeout(sonder, 1000); }
                                } else { vuIndisponible = true; setTimeout(sonder, 1000); }
                            })
                            .catch(function() { vuIndisponible = true; setTimeout(sonder, 1000); });
                    }
                    setTimeout(sonder, 500);
                })();
            `;
            window.parent.document.body.appendChild(s);
            </script>
            """,
            height=0,
        )

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

    st.divider()
    st.subheader("🔗 URL publique de l'application")
    st.caption(
        "Adresse à laquelle l'application est accessible (ex. `https://xxx.streamlit.app`), réglage "
        "global. Utilisée pour construire un lien direct vers la page **Historique** dans les mails "
        "de notification d'échec du fetch automatique — laisser vide pour un simple rappel textuel, "
        "sans lien cliquable."
    )
    url_actuelle = get_url_app()
    nouvelle_url = st.text_input("URL de l'application", value=url_actuelle, placeholder="https://xxx.streamlit.app")
    if st.button("💾 Enregistrer l'URL"):
        set_url_app(nouvelle_url)
        st.session_state["_url_app_enregistree"] = True
        st.rerun()
    if st.session_state.pop("_url_app_enregistree", None):
        st.success("✅ URL enregistrée.")
