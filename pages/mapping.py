"""
Page de paramétrage des tables de correspondance utilisées par la moulinette
de conversion LightSpeed → Pennylane, pour le client actuellement sélectionné.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core.client_store import get_client
from core.mapping_store import load_mappings, reset_to_empty, save_mappings, seed_with_examples
from core.timezone import now_local
from core.ui_common import select_client


def _as_editable_df(rows: list[dict], columns: list[str], tri: str | list[str] | None = None) -> pd.DataFrame:
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
    partout, plutôt que de le laisser deviner par pandas.

    tri : colonne(s) selon laquelle trier alphabétiquement (insensible à la
    casse) avant affichage. Streamlit désactive le tri interactif (clic sur
    l'en-tête) dès que num_rows="dynamic" (nécessaire ici pour pouvoir
    ajouter/supprimer des lignes) : impossible d'avoir les deux à la fois côté
    composant, donc on trie nous-mêmes la donnée en amont plutôt que de
    sacrifier l'ajout/suppression en ligne."""
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows).reindex(columns=columns).fillna("").astype(str)
    if tri:
        cles = [tri] if isinstance(tri, str) else tri
        df = df.sort_values(by=cles, key=lambda s: s.str.casefold(), kind="stable").reset_index(drop=True)
    return df


def _csv_bytes(df: pd.DataFrame) -> bytes:
    """CSV au format Excel FR (BOM UTF-8, séparateur point-virgule, fin de
    ligne CRLF) — même convention que l'export Pennylane
    (core.pennylane_export.build_pennylane_csv), pour rester cohérent."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep=";", lineterminator="\r\n")
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _bouton_export_csv(df: pd.DataFrame, client_id: str, onglet_slug: str, onglet_libelle: str, key: str) -> None:
    """Bouton de téléchargement CSV d'un onglet, avec un nom de fichier qui
    précise le client et l'onglet d'origine : sans ça, plusieurs exports
    successifs (un par onglet, ou pour des clients différents) deviennent
    impossibles à distinguer une fois dans le dossier de téléchargements.
    Exporte le contenu **actuellement affiché** dans le tableau, y compris
    d'éventuelles modifications pas encore enregistrées."""
    horodatage = now_local().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        f"⬇️ Exporter « {onglet_libelle} » en CSV",
        data=_csv_bytes(df),
        file_name=f"table_correspondance_{client_id}_{onglet_slug}_{horodatage}.csv",
        mime="text/csv",
        key=key,
    )


def _options_avec_libelle(rows: list[dict], code_key: str, libelle_key: str) -> list[str]:
    """Options de menu déroulant "code - libellé" : lisible sans connaître les
    codes par cœur. Seul le code (avant le premier " - ") est réellement
    stocké au moment de l'enregistrement — cf. _code_depuis_affichage — le
    libellé n'est qu'un confort de lecture, jamais une donnée persistée."""
    out = []
    for r in rows:
        code = (r.get(code_key) or "").strip()
        if not code:
            continue
        libelle = (r.get(libelle_key) or "").strip()
        out.append(f"{code} - {libelle}" if libelle else code)
    return out


def _affichage_depuis_code(code: str, rows: list[dict], code_key: str, libelle_key: str) -> str:
    """Convertit un code déjà enregistré vers sa forme d'affichage "code -
    libellé" si son libellé est retrouvé dans le référentiel fourni, sinon
    renvoie le code tel quel — une valeur déjà enregistrée n'est jamais
    perdue/vidée, même si elle ne correspond plus à rien dans le référentiel."""
    code = (code or "").strip()
    if not code:
        return code
    for r in rows:
        if (r.get(code_key) or "").strip() == code:
            libelle = (r.get(libelle_key) or "").strip()
            return f"{code} - {libelle}" if libelle else code
    return code


def _code_depuis_affichage(valeur: str) -> str:
    """Ne garde que la partie code d'une valeur affichée "code - libellé" :
    tout ce qui suit le premier " - " n'est qu'esthétique, jamais stocké."""
    return (valeur or "").split(" - ", 1)[0].strip()


client_id = select_client()

st.title("🗂️ Table de correspondance")
st.caption(
    "LightSpeed ne gère pas de code analytique : c'est la combinaison "
    "**compte comptable × point de vente × département** qui permet de le reconstituer. "
    "Paramétrez ici les tables utilisées par la conversion, propres au client sélectionné. "
    "Les réglages généraux (code journal, compte d'écart...) se trouvent page **Réglages**, "
    "où se trouve aussi l'export complet (.xlsx, tous les onglets) — onglet **Sauvegarde**."
)

if client_id is None:
    st.stop()

client = get_client(client_id)
mappings = load_mappings(client_id)

(
    tab_pdv,
    tab_comptes,
    tab_codes_analytiques,
    tab_departements,
    tab_paiement,
    tab_paiement_ignores,
    tab_tva,
    tab_attribution,
) = st.tabs(
    [
        "Points de vente",
        "Comptes de vente PL",
        "Codes Analytique PL",
        "Départements LS",
        "Moyens de paiements",
        "Moyens de paiements ignorés",
        "Taux de TVA",
        "Attribution analytique",
    ]
)

with tab_pdv:
    st.markdown(
        "Liste des points de vente (sites, salles, activités...) rencontrés dans les exports LightSpeed. "
        "L'**adresse mail de réception** est optionnelle : si elle est renseignée, tout export LightSpeed reçu "
        "automatiquement à cette adresse sera rattaché à ce point de vente (voir la moulinette de "
        "réception automatique). Elle doit être unique entre tous les clients. "
        "L'**adresse mail de résultat** est optionnelle elle aussi : par défaut, le CSV Pennylane et le "
        "récapitulatif sont renvoyés à l'adresse de réception (celle qui a reçu l'export) ; renseignez-la "
        "pour les envoyer ailleurs à la place (ex. la comptable, une adresse de suivi dédiée...). Plusieurs "
        "destinataires possibles, séparés par une virgule ou un point-virgule."
    )
    edited_pdv_df = st.data_editor(
        _as_editable_df(
            mappings.get("points_de_vente", []),
            ["code", "libelle", "adresse_email", "adresse_resultat", "commentaires"],
            tri="code",
        ),
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
            "adresse_resultat": st.column_config.TextColumn(
                "Adresse mail de résultat (optionnelle)",
                help="Destinataire(s) du CSV Pennylane et du récapitulatif après conversion automatique — "
                "plusieurs adresses possibles, séparées par une virgule ou un point-virgule. "
                "Laisser vide pour répondre à l'adresse de réception (comportement par défaut).",
            ),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_pdv = edited_pdv_df.dropna(how="all").fillna("").to_dict("records")
    _bouton_export_csv(edited_pdv_df, client_id, "points_de_vente", "Points de vente", key="export_pdv")

with tab_comptes:
    st.markdown(
        "**Référentiel des comptes de vente Pennylane** (plan comptable), indépendant de LightSpeed. "
        "Sert uniquement à proposer une liste de comptes valides (menu déroulant, affiché « code - "
        "libellé » pour rester lisible) dans les onglets « Départements LS » et "
        "« Attribution analytique » — c'est *là-bas* que se fait le lien avec les catégories "
        "LightSpeed, pas ici."
    )
    edited_comptes_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_de_vente", []), ["compte", "libelle_compte", "commentaires"], tri="compte"
        ),
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
    _bouton_export_csv(edited_comptes_df, client_id, "comptes_de_vente", "Comptes de vente PL", key="export_comptes")
    # Les menus déroulants des autres onglets (ci-dessous) se basent volontairement sur l'état
    # ENREGISTRÉ (mappings, chargé une fois en haut de page) plutôt que sur edited_comptes (le
    # retour live de cet éditeur) : sinon, toute frappe ici fait varier la configuration des
    # colonnes des autres onglets à chaque rafraîchissement, ce qui leur fait perdre leur saisie
    # en cours côté Streamlit. Un compte tout juste ajouté n'apparaît donc dans les autres onglets
    # qu'après un premier clic sur « Enregistrer » — c'est le compromis retenu pour la stabilité.
    comptes_options = _options_avec_libelle(mappings.get("comptes_de_vente", []), "compte", "libelle_compte")

with tab_codes_analytiques:
    st.markdown(
        "**Référentiel pur des codes analytiques** existants côté Pennylane (code + description), "
        "indépendant de LightSpeed — la simple liste des codes valides. Sert de liste de choix dans "
        "l'onglet « Attribution analytique », qui décide *quand* utiliser quel code ; ce n'est pas le "
        "cas ici."
    )
    edited_codes_analytiques_df = st.data_editor(
        _as_editable_df(
            mappings.get("codes_analytiques", []),
            ["code_analytique", "description", "commentaires"],
            tri="code_analytique",
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_codes_analytiques",
        column_config={
            "code_analytique": st.column_config.TextColumn("Code analytique", required=True),
            "description": st.column_config.TextColumn("Description", required=True),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_codes_analytiques = edited_codes_analytiques_df.dropna(how="all").fillna("").to_dict("records")
    _bouton_export_csv(
        edited_codes_analytiques_df, client_id, "codes_analytiques", "Codes Analytique PL", key="export_codes_analytiques"
    )
    # Même choix que pour comptes_options ci-dessus : basé sur l'état enregistré, pas le live.
    # Pas de "code - description" ici (contrairement à comptes_options) : le code analytique EST
    # potentiellement déjà la chaîne longue à afficher (ex. "ASPP - Alcools & Cocktails alcoolisés"),
    # la description n'est qu'un complément d'information optionnel, pas systématiquement affiché.
    codes_analytiques_options = [
        c["code_analytique"] for c in mappings.get("codes_analytiques", []) if c.get("code_analytique")
    ]

with tab_departements:
    st.markdown(
        "Correspondance entre chaque **département LightSpeed** (colonne « Références comptables » "
        "de l'export — LightSpeed n'a pas de notion de catégorie distincte du département) et son "
        "**compte de vente** (choisi dans l'onglet « Comptes de vente PL »). Le **taux de TVA** "
        "ici est purement informatif : le taux réellement appliqué à chaque ligne vient du fichier "
        "LightSpeed lui-même, pas de cette table. Tout département rencontré dans un fichier importé "
        "et absent d'ici bloquera l'export ; un département présent mais sans compte choisi bloque "
        "également (mieux vaut bloquer que deviner)."
    )
    if not comptes_options:
        st.warning("Ajoutez d'abord des comptes dans l'onglet « Comptes de vente PL » pour pouvoir les choisir ici.")
    # Départements réellement affectés à au moins une ligne d'attribution analytique, tous
    # points de vente/comptes confondus - purement informatif, calculé à la volée (jamais
    # enregistré), pour repérer d'un coup d'œil un département encore orphelin.
    departements_affectes = {
        (a.get("categorie_lightspeed") or "").strip().casefold()
        for a in mappings.get("comptes_analytiques", [])
        if a.get("categorie_lightspeed")
    }
    departements_source = [
        {
            **d,
            "compte": _affichage_depuis_code(
                d.get("compte", ""), mappings.get("comptes_de_vente", []), "compte", "libelle_compte"
            ),
            "affecte": "✅" if (d.get("categorie_lightspeed") or "").strip().casefold() in departements_affectes else "⚠️ aucune attribution",
        }
        for d in mappings.get("departements", [])
    ]
    edited_departements_df = st.data_editor(
        _as_editable_df(
            departements_source,
            ["categorie_lightspeed", "compte", "taux_tva", "affecte", "commentaires"],
            tri="categorie_lightspeed",
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_departements",
        disabled=["affecte"],
        column_config={
            "categorie_lightspeed": st.column_config.TextColumn("Département LightSpeed", required=True),
            "compte": st.column_config.SelectboxColumn("Compte de vente", options=comptes_options),
            "taux_tva": st.column_config.SelectboxColumn(
                "Taux TVA nominal (informatif)", options=["0%", "5.5%", "10%", "20%"]
            ),
            "affecte": st.column_config.TextColumn(
                "Attribution analytique",
                help="Ce département apparaît-il dans au moins une ligne de l'onglet « Attribution "
                "analytique » (tous points de vente/comptes confondus) ? Colonne informative, non enregistrée.",
            ),
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_departements = [
        {"categorie_lightspeed": d.get("categorie_lightspeed", ""), "compte": _code_depuis_affichage(d.get("compte", "")),
         "taux_tva": d.get("taux_tva", ""), "commentaires": d.get("commentaires", "")}
        for d in edited_departements_df.dropna(how="all").fillna("").to_dict("records")
    ]
    _bouton_export_csv(edited_departements_df, client_id, "departements", "Départements LS", key="export_departements")

with tab_paiement:
    st.markdown(
        "Correspondance entre chaque **mode de paiement LightSpeed** (Carte bleue, Espèces, "
        "Deliveroo, UberEats...) et son **compte de contrepartie** (banque, caisse, créance "
        "plateforme) dans Pennylane. Un mode de paiement non mappé bloque également l'export "
        "(l'écriture serait déséquilibrée)."
    )
    edited_paiement_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_paiement", []),
            ["mode_paiement", "compte", "libelle_compte", "commentaires"],
            tri="mode_paiement",
        ),
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
    _bouton_export_csv(edited_paiement_df, client_id, "moyens_paiement", "Moyens de paiements", key="export_paiement")

with tab_paiement_ignores:
    st.markdown(
        "Intitulés de **mode de paiement** (bloc « Modes de paiement » de l'export LightSpeed "
        "uniquement) à **exclure totalement** de l'écriture générée : aucune ligne de débit/crédit "
        "n'est créée pour eux, contrairement à un mode non mappé dans l'onglet précédent qui bloque "
        "l'export. Correspondance **exacte** (insensible à la casse et aux espaces superflus). "
        "⚠️ À réserver aux lignes sans valeur comptable propre — jamais pour écarter un montant réel "
        "dont on ne sait juste pas où l'imputer (ça, c'est le rôle du compte d'écart, page Réglages)."
    )
    edited_paiement_ignores_df = st.data_editor(
        _as_editable_df(
            mappings.get("modes_paiement_ignores", []), ["mode_paiement", "commentaires"], tri="mode_paiement"
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_paiement_ignores",
        column_config={
            "mode_paiement": st.column_config.TextColumn(
                "Mode de paiement à ignorer", required=True, help="Intitulé exact tel qu'il apparaît dans l'export LightSpeed."
            ),
            "commentaires": st.column_config.TextColumn("Commentaires", help="Pourquoi cette ligne est ignorée."),
        },
    )
    edited_paiement_ignores = edited_paiement_ignores_df.dropna(how="all").fillna("").to_dict("records")
    _bouton_export_csv(
        edited_paiement_ignores_df, client_id, "moyens_paiement_ignores", "Moyens de paiements ignorés",
        key="export_paiement_ignores",
    )

with tab_tva:
    st.markdown("Compte de **TVA collectée** à utiliser pour chaque taux de TVA rencontré dans les ventes.")
    edited_tva_df = st.data_editor(
        _as_editable_df(
            mappings.get("comptes_tva", []), ["taux", "compte", "libelle_compte", "commentaires"], tri="taux"
        ),
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
    _bouton_export_csv(edited_tva_df, client_id, "taux_tva", "Taux de TVA", key="export_tva")

with tab_attribution:
    st.markdown(
        "Pour un **compte comptable**, un **point de vente** et un **département LightSpeed** donnés, "
        "quel **code analytique** (choisi dans l'onglet « Codes Analytique PL ») appliquer. C'est cette "
        "table qui « rejoue » l'analytique que LightSpeed ne fournit pas — les trois critères sont "
        "nécessaires : un même compte peut porter un code analytique différent selon le département, "
        "même sur un seul et même point de vente (ex. un compte de boisson peut être « Sommellerie » "
        "ou « Bar » selon le département d'origine). Toute combinaison rencontrée à la conversion et "
        "absente d'ici bloquera l'export.\n\n"
        "⚠️ Cette table part de l'hypothèse que la combinaison (compte, point de vente, département) "
        "suffit à déterminer le code analytique dans tous les cas — à valider avec un exemple réel : "
        "si certains cas s'avèrent plus dynamiques (règle non réductible à cette combinaison), cette "
        "table ne sera pas suffisante et il faudra revoir l'approche.\n\n"
        "**Aucun bouton « Enregistrer » ici** : chaque action (créer, modifier, supprimer) écrit "
        "directement dans le référentiel, indépendamment du bouton tout en bas de page (qui ne "
        "concerne que les autres onglets)."
    )
    # Même choix que pour comptes_options : basé sur l'état enregistré, pas le live des autres onglets.
    departements_options = [
        d["categorie_lightspeed"] for d in mappings.get("departements", []) if d.get("categorie_lightspeed")
    ]
    pdv_options = [p["code"] for p in mappings.get("points_de_vente", [])]
    if not codes_analytiques_options:
        st.warning("Ajoutez d'abord des codes dans l'onglet « Codes Analytique PL » pour pouvoir les choisir ici.")

    # --- Tableau des groupes (1 ligne = 1 attribution), sélectionnable -----------------
    groupes: dict[tuple[str, str, str, str], list[str]] = {}
    for a in mappings.get("comptes_analytiques", []):
        cle = (a.get("point_de_vente", ""), a.get("compte", ""), a.get("code_analytique", ""), a.get("famille", ""))
        groupes.setdefault(cle, []).append(a.get("categorie_lightspeed", ""))
    groupes_keys = sorted(groupes.keys())
    departements_connus = {d.strip().casefold() for d in departements_options}

    def _departements_affiches(deps: list[str]) -> str:
        parties = []
        for d in sorted(deps, key=str.casefold):
            parties.append(f"⚠️ {d}" if d.strip().casefold() not in departements_connus else d)
        return ", ".join(parties)

    groupes_df = pd.DataFrame(
        [
            {
                "Point de vente": pdv,
                "Compte": _affichage_depuis_code(compte, mappings.get("comptes_de_vente", []), "compte", "libelle_compte"),
                # Le code analytique est affiché tel qu'enregistré, sans concaténer la description :
                # c'est le code lui-même qui porte l'information complète (ex. "ASPP - Alcools &
                # Cocktails alcoolisés"), la description n'est qu'un complément optionnel, pas
                # systématiquement affiché ici.
                "Code analytique": code,
                "Famille": famille,
                "Départements": _departements_affiches(groupes[(pdv, compte, code, famille)]),
            }
            for (pdv, compte, code, famille) in groupes_keys
        ]
    )

    st.markdown("#### Attributions existantes")
    st.caption(
        "Clique sur une ligne pour la modifier ou la supprimer dans le formulaire ci-dessous. "
        "⚠️ devant un département = introuvable dans « Départements LS », probable faute de frappe."
    )
    if groupes_df.empty:
        st.info("Aucune attribution enregistrée pour l'instant.")
        selection_event = None
    else:
        # Streamlit interdit toute écriture dans st.session_state pour ce type de widget (même
        # avant son instanciation, selon la version) : impossible de désélectionner une ligne
        # "de force" après enregistrement/suppression. On force donc un nouveau widget (donc sans
        # sélection) en faisant varier sa clé, via un compteur - lui, un simple session_state
        # ordinaire, s'incrémente sans restriction.
        table_key = f"table_groupes_attribution_{st.session_state.get('_version_table_attribution', 0)}"
        selection_event = st.dataframe(
            groupes_df,
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key=table_key,
            # Sans largeur explicite, Streamlit compresse chaque colonne par défaut : "Compte" et
            # "Code analytique" ("ASPP - Alcools & Cocktails alcoolisés") se retrouvaient coupés à
            # l'affichage bien que la donnée complète soit là — impossible de distinguer deux lignes
            # partageant le même préfixe de code. La valeur n'était jamais tronquée, seulement son
            # rendu visuel.
            column_config={
                "Compte": st.column_config.TextColumn("Compte", width="large"),
                "Code analytique": st.column_config.TextColumn("Code analytique", width="large"),
                "Départements": st.column_config.TextColumn("Départements", width="large"),
            },
        )

    if not groupes_df.empty:
        _bouton_export_csv(groupes_df, client_id, "attribution_analytique", "Attribution analytique", key="export_attribution")

    selected_idx = None
    if selection_event is not None and selection_event["selection"]["rows"]:
        selected_idx = selection_event["selection"]["rows"][0]
    selected_key = groupes_keys[selected_idx] if selected_idx is not None else None
    selected_departements = sorted(groupes[selected_key], key=str.casefold) if selected_key else []

    # --- Formulaire unique : édite la ligne sélectionnée, ou en crée une nouvelle ------
    st.markdown(f"#### {'Modifier l’attribution sélectionnée' if selected_key else 'Nouvelle attribution'}")
    if selected_key and any(d.strip().casefold() not in departements_connus for d in selected_departements):
        st.caption(
            "⚠️ Un département introuvable dans le référentiel ne peut pas être présélectionné ici : "
            "s'il n'est pas r'ajouté manuellement dans la liste ci-dessous, il sera retiré à l'enregistrement."
        )

    def _index_ou_none(valeur_code: str, options: list[str]) -> int | None:
        for i, o in enumerate(options):
            if _code_depuis_affichage(o) == valeur_code:
                return i
        return None

    with st.form("form_attribution", clear_on_submit=False):
        fc1, fc2 = st.columns(2)
        f_pdv = fc1.selectbox(
            "Point de vente",
            options=pdv_options,
            index=pdv_options.index(selected_key[0]) if selected_key and selected_key[0] in pdv_options else None,
            placeholder="Choisir un point de vente",
        )
        f_famille = fc2.text_input(
            "Famille analytique",
            value=selected_key[3] if selected_key else mappings.get("parametres", {}).get(
                "famille_categorie_analytique", "POINT_DE_VENTE"
            ),
        )
        fc3, fc4 = st.columns(2)
        f_compte_affiche = fc3.selectbox(
            "Compte comptable",
            options=comptes_options,
            index=_index_ou_none(selected_key[1], comptes_options) if selected_key else None,
            placeholder="Choisir un compte",
        )
        f_code_affiche = fc4.selectbox(
            "Code analytique",
            options=codes_analytiques_options,
            # Correspondance exacte, pas _index_ou_none (qui coupe au premier " - ") : le code
            # analytique peut légitimement contenir lui-même un tiret (ex. "ASPP - Alcools & ...").
            index=codes_analytiques_options.index(selected_key[2])
            if selected_key and selected_key[2] in codes_analytiques_options else None,
            placeholder="Choisir un code",
        )
        f_departements = st.multiselect(
            "Département LightSpeed (un ou plusieurs)",
            options=departements_options,
            default=[d for d in selected_departements if d in departements_options],
        )
        fb1, fb2 = st.columns(2)
        submit_save = fb1.form_submit_button(
            "💾 Enregistrer les modifications" if selected_key else "➕ Créer l'attribution", type="primary"
        )
        submit_delete = fb2.form_submit_button("🗑️ Supprimer ce groupe", disabled=not selected_key)

    def _appartient_au_groupe(ligne: dict, cle: tuple[str, str, str, str]) -> bool:
        return (
            ligne.get("point_de_vente") == cle[0]
            and ligne.get("compte") == cle[1]
            and ligne.get("code_analytique") == cle[2]
            and ligne.get("famille") == cle[3]
        )

    if submit_delete and selected_key:
        mappings_actuels = load_mappings(client_id)
        lignes = mappings_actuels.get("comptes_analytiques", [])
        lignes[:] = [l for l in lignes if not _appartient_au_groupe(l, selected_key)]
        save_mappings(client_id, mappings_actuels)
        st.session_state.pop("resultats", None)
        st.session_state["_version_table_attribution"] = st.session_state.get("_version_table_attribution", 0) + 1
        st.success("Attribution supprimée.")
        st.rerun()

    if submit_save:
        if not (f_compte_affiche and f_pdv and f_departements and f_code_affiche):
            st.error("Compte, point de vente, au moins un département et code analytique sont obligatoires.")
        else:
            f_compte = _code_depuis_affichage(f_compte_affiche)
            # f_code_affiche est déjà le code brut (codes_analytiques_options n'est plus une liste
            # "code - description") : pas de _code_depuis_affichage ici, qui couperait à tort un
            # code analytique contenant lui-même un tiret.
            f_code = f_code_affiche
            mappings_actuels = load_mappings(client_id)
            lignes = mappings_actuels.setdefault("comptes_analytiques", [])

            # Commentaires existants à préserver pour les départements qui restent dans le groupe.
            commentaires_existants = {}
            if selected_key:
                for l in lignes:
                    if _appartient_au_groupe(l, selected_key):
                        commentaires_existants[l.get("categorie_lightspeed")] = l.get("commentaires", "")
                # Remplace entièrement l'ancien groupe : les départements retirés du formulaire
                # ne sont pas recréés, ce qui les retire du groupe (y compris un intrus non
                # présélectionnable, cf. avertissement ci-dessus).
                lignes[:] = [l for l in lignes if not _appartient_au_groupe(l, selected_key)]

            for dep in f_departements:
                lignes.append(
                    {
                        "compte": f_compte,
                        "point_de_vente": f_pdv,
                        "categorie_lightspeed": dep,
                        "famille": f_famille,
                        "code_analytique": f_code,
                        "commentaires": commentaires_existants.get(dep, ""),
                    }
                )

            save_mappings(client_id, mappings_actuels)
            st.session_state.pop("resultats", None)
            st.session_state["_version_table_attribution"] = st.session_state.get("_version_table_attribution", 0) + 1
            st.success(f"Attribution enregistrée ({len(f_departements)} département(s)).")
            st.rerun()

st.divider()
b1, b2, _ = st.columns([1, 1, 4])
if b1.button("💾 Enregistrer", type="primary"):
    save_mappings(
        client_id,
        {
            **mappings,
            "points_de_vente": edited_pdv,
            "comptes_de_vente": edited_comptes,
            "departements": edited_departements,
            "codes_analytiques": edited_codes_analytiques,
            # comptes_analytiques n'est pas listé ici : géré directement (créé/modifié/supprimé
            # immédiatement) par le formulaire de l'onglet "Attribution analytique", pas par ce
            # bouton - **mappings ci-dessus porte déjà sa valeur à jour.
            "comptes_paiement": edited_paiement,
            "modes_paiement_ignores": edited_paiement_ignores,
            "comptes_tva": edited_tva,
        },
    )
    st.session_state.pop("resultats", None)
    st.success("Tables de correspondance enregistrées.")

_cle_confirmation_vidage = f"confirmation_vidage_{client_id}"

if b2.button("🗑️ Vider ce référentiel"):
    st.session_state[_cle_confirmation_vidage] = True

if st.session_state.get(_cle_confirmation_vidage):
    st.warning(
        f"⚠️ Ceci supprime **définitivement** tout le référentiel de « {client['nom']} » "
        "(comptes, départements, attributions analytiques, modes de paiement, TVA...) — "
        "aucun moyen de revenir en arrière. Confirmer ?"
    )
    cv1, cv2, _ = st.columns([1, 1, 4])
    if cv1.button("✅ Oui, tout supprimer", type="primary"):
        reset_to_empty(client_id)
        st.session_state.pop("resultats", None)
        st.session_state.pop(_cle_confirmation_vidage, None)
        st.rerun()
    if cv2.button("Annuler"):
        st.session_state.pop(_cle_confirmation_vidage, None)
        st.rerun()
