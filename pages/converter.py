"""
Convertisseur LightSpeed → Pennylane
=====================================
Page principale : import du fichier export comptable LightSpeed, application
de la moulinette de conversion, contrôle du chiffre d'affaires et export du
fichier CSV d'import avancé Pennylane. Chaque conversion est archivée dans
l'historique du client sélectionné.

- La table de correspondance se gère depuis « Table de correspondance ».
- Les clients se gèrent depuis « Clients ».
- L'historique et le journal d'anomalies se consultent depuis « Historique ».
"""
from __future__ import annotations

import datetime as dt

import streamlit as st
import streamlit.components.v1 as components

from core.converter import convert
from core.history_store import record_conversion
from core.lightspeed_parser import LightspeedParseError, parse_lightspeed_export
from core.mapping_store import load_mappings
from core.pennylane_export import build_pennylane_csv
from core.timezone import now_local
from core.ui_common import select_client



# Mots-clés strictement requis pour suggérer le point de vente "BAR" : le nom
# du fichier LightSpeed ne contient pas toujours "bar" (ex. il peut porter le
# nom de la marque du bar, "UTOPIC") mais un rapprochement générique avec le
# code/libellé configuré était trop permissif (faux positifs). Restreint donc
# ce point de vente précis à une présence explicite de l'un de ces mots.
MOTS_CLES_BAR = ("bar", "utopic")


def _deviner_index_pdv(filename: str, points_de_vente: list[dict]) -> int:
    """Propose un point de vente par défaut à partir du **nom de fichier brut**
    (jamais du contenu de l'export, qui ne porte aucune information de point
    de vente) : recherche le code ou le libellé de chaque point de vente
    configuré, en toutes lettres, dans le nom de fichier - sauf pour "BAR",
    restreint à MOTS_CLES_BAR (voir sa docstring). En cas de plusieurs
    correspondances (ex. « BAR » et « BARF » matchent tous les deux un nom
    contenant « barf »), retient la plus longue, plus spécifique. Simple
    suggestion pré-remplie dans le menu déroulant, jamais imposée : à
    valider/corriger manuellement avant conversion."""
    nom_normalise = filename.strip().lower()
    meilleur_index, meilleure_longueur = 0, 0
    for i, p in enumerate(points_de_vente):
        code_normalise = p.get("code", "").strip().lower()
        libelle_normalise = p.get("libelle", "").strip().lower()
        if "bar" in (code_normalise, libelle_normalise):
            candidats = MOTS_CLES_BAR
        else:
            candidats = (p.get("code", ""), p.get("libelle", ""))
        for candidat in candidats:
            candidat_normalise = candidat.strip().lower()
            if candidat_normalise and candidat_normalise in nom_normalise and len(candidat_normalise) > meilleure_longueur:
                meilleur_index, meilleure_longueur = i, len(candidat_normalise)
    return meilleur_index


client_id = select_client()

st.title("🧾 Convertisseur LightSpeed → Pennylane")
st.caption(
    "Importez un ou plusieurs exports comptables LightSpeed, associez chaque fichier à son "
    "point de vente, puis générez le fichier CSV d'import avancé Pennylane avec les codes "
    "analytiques rejoués automatiquement."
)

if client_id is None:
    st.info("Créez un client (menu latéral, ou page **Clients**) avant de pouvoir convertir un fichier.")
    st.stop()

mappings = load_mappings(client_id)
points_de_vente = mappings.get("points_de_vente", [])
pdv_codes = [p["code"] for p in points_de_vente]

if not pdv_codes:
    st.warning(
        "Aucun point de vente n'est encore paramétré pour ce client. Rendez-vous sur la page "
        "**Table de correspondance** pour en créer avant de convertir un fichier."
    )

st.subheader("Importer le ou les exports LightSpeed")

# Bloc de dépôt agrandi de 50% (plus facile à viser) et libellés traduits :
# st.file_uploader ne propose ni paramètre de taille ni de traduction de ses
# textes intégrés ("Upload", "200MB per file..."), ce qui impose un correctif
# CSS (taille) + JS (traduction, rejouée à chaque rendu puisque Streamlit
# reconstruit le DOM à chaque interaction).
st.markdown(
    """
    <style>
    div[data-testid="stFileUploaderDropzone"] {
        min-height: 102px !important; /* 68px d'origine, +50% */
        padding: 24px !important;
    }
    div[data-testid="stFileUploaderDropzone"] span[data-testid="stIconMaterial"] {
        font-size: 1.5em !important;
    }
    div[data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] p {
        font-size: 1.1rem !important;
    }
    div[data-testid="stFileUploaderDropzoneInstructions"] span {
        font-size: 1.05rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
components.html(
    r"""
    <script>
    const traductions = [
        [/^Upload$/, "Parcourir les fichiers"],
        [/^Browse files$/, "Parcourir les fichiers"],
        [/^Drag and drop file(s)? here$/, "Glissez-déposez votre fichier ici"],
        [/^(\d+)MB per file(.*)$/, "$1 Mo par fichier$2"],
    ];

    function traduireNoeud(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const original = node.textContent;
            const cible = original.trim();
            for (const [motif, remplacement] of traductions) {
                if (motif.test(cible)) {
                    const nouveau = original.replace(motif, remplacement);
                    if (nouveau !== original) node.textContent = nouveau;
                    return;
                }
            }
        } else {
            node.childNodes.forEach(traduireNoeud);
        }
    }

    function traduireTout() {
        traduireNoeud(window.parent.document.body);
    }

    new MutationObserver(traduireTout).observe(window.parent.document.body, {
        childList: true, subtree: true, characterData: true,
    });
    traduireTout();
    </script>
    """,
    height=0,
)

uploaded_files = st.file_uploader(
    "Fichier(s) export comptable LightSpeed (.xls / .xlsx / .csv)",
    type=["xls", "xlsx", "csv"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.subheader("2. Associer chaque fichier à son point de vente")
    file_configs = []
    for uf in uploaded_files:
        raw = uf.getvalue()
        try:
            export = parse_lightspeed_export(raw, uf.name)
        except LightspeedParseError as e:
            st.error(f"**{uf.name}** : {e}")
            continue

        with st.expander(f"📄 {uf.name}", expanded=True):
            c1, c2, c3, c4 = st.columns([2, 1.4, 1.4, 1.6])
            default_pdv_index = _deviner_index_pdv(uf.name, points_de_vente)
            with c1:
                pdv = st.selectbox(
                    "Point de vente",
                    options=pdv_codes if pdv_codes else ["—"],
                    index=default_pdv_index if pdv_codes else 0,
                    key=f"pdv_{uf.name}",
                    help="Ce code, combiné au compte comptable, détermine le code analytique généré.",
                )
            with c2:
                default_date = now_local().date()
                if export.date_detectee:
                    try:
                        d, m, y = export.date_detectee.split("/")
                        default_date = dt.date(2000 + int(y), int(m), int(d))
                    except Exception:
                        pass
                date_piece = st.date_input("Date de pièce", value=default_date, key=f"date_{uf.name}")
            with c3:
                numero_piece = st.text_input(
                    "Numéro de pièce", value=f"LS-{date_piece.strftime('%y%m%d')}-{pdv}", key=f"num_{uf.name}"
                )
            with c4:
                code_journal = st.text_input(
                    "Code journal", value=mappings["parametres"].get("code_journal", "VT"), key=f"jrn_{uf.name}"
                )

            # Contrôle de premier niveau, indépendant du mapping comptable : le
            # total des ventes TTC déclaré par LightSpeed doit correspondre au
            # total des encaissements.
            if export.ventes_encaissements_coherents:
                st.success(
                    f"✅ Ventes/encaissements cohérents à la source — "
                    f"Ventes TTC {export.ca_ttc:,.2f} € vs Encaissements {export.total_paiements:,.2f} €"
                    + (f" (report de {export.total_reports:+.2f} € pris en compte)" if export.total_reports else "")
                )
            else:
                st.error(
                    f"❌ Incohérence dans le fichier source lui-même : Ventes TTC {export.ca_ttc:,.2f} € vs "
                    f"Encaissements {export.total_paiements:,.2f} € (écart {export.ecart_ventes_encaissements:+.2f} €"
                    f" non expliqué par le report déclaré de {export.total_reports:+.2f} €). "
                    "Fichier à vérifier avant conversion."
                )

            cc1b, cc2b, cc3b = st.columns(3)
            cc1b.metric("CA HT (LightSpeed)", f"{export.ca_ht:,.2f} €".replace(",", " "))
            cc2b.metric("TVA collectée", f"{export.tva_totale:,.2f} €".replace(",", " "))
            cc3b.metric("Total TTC encaissé", f"{export.ca_ttc:,.2f} €".replace(",", " "))

            st.dataframe(
                [
                    {
                        "Catégorie": c.libelle,
                        "Qté": c.quantite,
                        "Total HT": c.total_ht,
                        "Taux TVA": c.taux_tva,
                        "TVA": c.montant_tva,
                        "Total TTC": c.total_ttc,
                        "⚠️ Taux ambigu": "oui" if c.taux_ambigu else "",
                    }
                    for c in export.categories
                ],
                use_container_width=True,
                hide_index=True,
            )

            file_configs.append(
                {
                    "export": export,
                    "raw": raw,
                    "point_de_vente": pdv,
                    "date_piece": date_piece.strftime("%d/%m/%y"),
                    "numero_piece": numero_piece,
                    "code_journal": code_journal,
                }
            )

    if file_configs:
        st.divider()
        st.subheader("3. Conversion et contrôle du chiffre d'affaires")

        if st.button("🔄 Lancer la conversion", type="primary"):
            resultats = []
            horodatage = now_local().strftime("%Y-%m-%d %H:%M:%S")
            for cfg in file_configs:
                res = convert(
                    cfg["export"],
                    mappings,
                    point_de_vente=cfg["point_de_vente"],
                    date_piece=cfg["date_piece"],
                    numero_piece=cfg["numero_piece"],
                    code_journal=cfg["code_journal"],
                )
                resultats.append((res, cfg["raw"]))
                # Chaque tentative de conversion est archivée immédiatement, y compris en
                # cas d'échec (mapping manquant, écriture déséquilibrée...) : l'historique
                # doit garder la trace des échecs pour pouvoir les expliquer a posteriori,
                # pas seulement des conversions réussies et téléchargées.
                csv_unitaire = build_pennylane_csv([res])
                record_conversion(client_id, res, cfg["raw"], csv_unitaire, horodatage)
            st.session_state["resultats"] = resultats

        resultats_bruts = st.session_state.get("resultats")
        if resultats_bruts:
            resultats = [r for r, _ in resultats_bruts]
            total_ca_source = round(sum(r.ca_ht_source for r in resultats), 2)
            total_ca_genere = round(sum(r.ca_ht_genere for r in resultats), 2)
            total_debit = round(sum(r.total_debit for r in resultats), 2)
            total_credit = round(sum(r.total_credit for r in resultats), 2)
            ca_ok = abs(total_ca_source - total_ca_genere) < 0.01
            eq_ok = abs(total_debit - total_credit) < 0.01

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("CA HT fichier(s) LightSpeed", f"{total_ca_source:,.2f} €".replace(",", " "))
            m2.metric(
                "CA HT fichier Pennylane généré",
                f"{total_ca_genere:,.2f} €".replace(",", " "),
                delta=f"{total_ca_genere - total_ca_source:+.2f} €",
                delta_color="off" if ca_ok else "inverse",
            )
            m3.metric("Total Débit", f"{total_debit:,.2f} €".replace(",", " "))
            m4.metric(
                "Total Crédit",
                f"{total_credit:,.2f} €".replace(",", " "),
                delta="Équilibré ✅" if eq_ok else f"Écart {total_credit - total_debit:+.2f} €",
                delta_color="off" if eq_ok else "inverse",
            )

            if ca_ok:
                st.success("✅ Le chiffre d'affaires du fichier généré correspond exactement au fichier importé : aucune perte d'information.")
            else:
                st.error(
                    "❌ Le CA généré diffère du CA source : des catégories n'ont probablement pas de correspondance "
                    "dans la table « Comptes de vente ». Voir les avertissements ci-dessous."
                )

            for res, _raw in resultats_bruts:
                with st.expander(
                    f"Détail — {res.source_filename} ({res.point_de_vente}) : "
                    f"{'✅' if res.ca_ok and res.equilibre_ok and res.sans_erreur else '⚠️'}",
                    expanded=not (res.ca_ok and res.equilibre_ok and res.sans_erreur),
                ):
                    for e in res.erreurs:
                        st.error(e)
                    for a in res.avertissements:
                        st.warning(a)
                    if res.sans_erreur and not res.avertissements:
                        st.success("Aucune anomalie détectée sur ce fichier.")
                    st.dataframe(res.lignes, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("4. Télécharger le fichier Pennylane")
            tous_ok = all(r.sans_erreur for r in resultats)
            csv_bytes = build_pennylane_csv(resultats)
            fname = f"import_pennylane_{now_local().strftime('%Y%m%d')}.csv"

            st.download_button(
                "⬇️ Télécharger le fichier d'import Pennylane (.csv)",
                data=csv_bytes,
                file_name=fname,
                mime="text/csv",
                type="primary",
                disabled=not tous_ok,
            )

            if not tous_ok:
                st.info("Corrigez les erreurs listées ci-dessus (mapping manquant) avant de pouvoir télécharger le fichier.")
            st.caption("📁 Cette tentative de conversion a été archivée dans l'historique de ce client (page « Historique »).")
else:
    st.info("Déposez un ou plusieurs fichiers d'export LightSpeed pour démarrer.")
