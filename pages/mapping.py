"""
Page de paramétrage des tables de correspondance utilisées par la moulinette
de conversion LightSpeed → Pennylane, pour le client actuellement sélectionné.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.mapping_store import (
    find_code_analytique,
    load_mappings,
    reset_to_empty,
    save_mappings,
    seed_with_examples,
)
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
    "Les réglages généraux (code journal, compte d'écart...) se trouvent page **Réglages**."
)

if client_id is None:
    st.stop()

mappings = load_mappings(client_id)

(
    tab_pdv,
    tab_comptes,
    tab_departements,
    tab_codes_analytiques,
    tab_attribution,
    tab_paiement,
    tab_paiement_ignores,
    tab_tva,
) = st.tabs(
    [
        "Points de vente",
        "Comptes de vente",
        "Départements LightSpeed",
        "Codes analytiques",
        "Attribution analytique",
        "Contreparties de paiement",
        "Modes de paiement ignorés",
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
        _as_editable_df(
            mappings.get("points_de_vente", []), ["code", "libelle", "adresse_email", "commentaires"], tri="code"
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
            "commentaires": st.column_config.TextColumn("Commentaires"),
        },
    )
    edited_pdv = edited_pdv_df.dropna(how="all").fillna("").to_dict("records")

with tab_comptes:
    st.markdown(
        "**Référentiel des comptes de vente Pennylane** (plan comptable), indépendant de LightSpeed. "
        "Sert uniquement à proposer une liste de comptes valides (menu déroulant, affiché « code - "
        "libellé » pour rester lisible) dans les tables « Départements LightSpeed » et "
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
    # Les menus déroulants des autres onglets (ci-dessous) se basent volontairement sur l'état
    # ENREGISTRÉ (mappings, chargé une fois en haut de page) plutôt que sur edited_comptes (le
    # retour live de cet éditeur) : sinon, toute frappe ici fait varier la configuration des
    # colonnes des autres onglets à chaque rafraîchissement, ce qui leur fait perdre leur saisie
    # en cours côté Streamlit. Un compte tout juste ajouté n'apparaît donc dans les autres onglets
    # qu'après un premier clic sur « Enregistrer » — c'est le compromis retenu pour la stabilité.
    comptes_options = _options_avec_libelle(mappings.get("comptes_de_vente", []), "compte", "libelle_compte")

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
    # Même choix que pour comptes_options ci-dessus : basé sur l'état enregistré, pas le live.
    codes_analytiques_options = _options_avec_libelle(
        mappings.get("codes_analytiques", []), "code_analytique", "description"
    )

with tab_attribution:
    st.markdown(
        "Pour un **compte comptable**, un **point de vente** et un **département LightSpeed** donnés, "
        "quel **code analytique** (choisi dans l'onglet précédent) appliquer. C'est cette table qui "
        "« rejoue » l'analytique que LightSpeed ne fournit pas — les trois critères sont nécessaires : "
        "un même compte peut porter un code analytique différent selon le département, même sur un "
        "seul et même point de vente (ex. un compte de boisson peut être « Sommellerie » ou « Bar » "
        "selon le département d'origine). Toute combinaison rencontrée à la conversion et absente "
        "d'ici bloquera l'export.\n\n"
        "⚠️ Cette table part de l'hypothèse que la combinaison (compte, point de vente, département) "
        "suffit à déterminer le code analytique dans tous les cas — à valider avec un exemple réel : "
        "si certains cas s'avèrent plus dynamiques (règle non réductible à cette combinaison), cette "
        "table ne sera pas suffisante et il faudra revoir l'approche."
    )
    # Même choix que pour comptes_options : basé sur l'état enregistré, pas le live des autres onglets.
    departements_options = [
        d["categorie_lightspeed"] for d in mappings.get("departements", []) if d.get("categorie_lightspeed")
    ]
    pdv_options = [p["code"] for p in mappings.get("points_de_vente", [])]
    if not codes_analytiques_options:
        st.warning("Ajoutez d'abord des codes dans l'onglet « Codes analytiques » pour pouvoir les choisir ici.")

    with st.expander("➕ Attribution groupée (plusieurs départements en une fois)"):
        st.caption(
            "Applique le même compte, la même famille et le même code analytique à plusieurs "
            "départements d'un coup, pour un point de vente donné — évite de créer une ligne par "
            "département à la main. Écrit directement dans le référentiel (indépendant du bouton "
            "« Enregistrer » tout en bas, qui ne concerne que les modifications faites dans la grille)."
        )
        with st.form("form_attribution_groupee", clear_on_submit=True):
            gc1, gc2 = st.columns(2)
            g_compte_affiche = gc1.selectbox(
                "Compte comptable", options=comptes_options, index=None, placeholder="Choisir un compte"
            )
            g_pdv = gc2.selectbox(
                "Point de vente", options=pdv_options, index=None, placeholder="Choisir un point de vente"
            )
            g_departements = st.multiselect("Départements LightSpeed (un ou plusieurs)", options=departements_options)
            gc3, gc4 = st.columns(2)
            g_code_affiche = gc3.selectbox(
                "Code analytique", options=codes_analytiques_options, index=None, placeholder="Choisir un code"
            )
            g_famille = gc4.text_input(
                "Famille analytique",
                value=mappings.get("parametres", {}).get("famille_categorie_analytique", "POINT_DE_VENTE"),
            )
            g_commentaires = st.text_input("Commentaires (optionnel)")
            submit_groupe = st.form_submit_button("Appliquer aux départements sélectionnés", type="primary")

        if submit_groupe:
            if not (g_compte_affiche and g_pdv and g_departements and g_code_affiche):
                st.error("Compte, point de vente, au moins un département et code analytique sont obligatoires.")
            else:
                g_compte = _code_depuis_affichage(g_compte_affiche)
                g_code = _code_depuis_affichage(g_code_affiche)
                mappings_actuels = load_mappings(client_id)
                lignes = mappings_actuels.setdefault("comptes_analytiques", [])
                nb_crees, nb_maj = 0, 0
                for dep in g_departements:
                    existante = find_code_analytique(mappings_actuels, g_compte, g_pdv, dep)
                    if existante is not None:
                        existante["famille"] = g_famille
                        existante["code_analytique"] = g_code
                        if g_commentaires:
                            existante["commentaires"] = g_commentaires
                        nb_maj += 1
                    else:
                        lignes.append(
                            {
                                "compte": g_compte,
                                "point_de_vente": g_pdv,
                                "categorie_lightspeed": dep,
                                "famille": g_famille,
                                "code_analytique": g_code,
                                "commentaires": g_commentaires,
                            }
                        )
                        nb_crees += 1
                save_mappings(client_id, mappings_actuels)
                st.session_state.pop("resultats", None)
                st.success(f"{nb_crees} ligne(s) créée(s), {nb_maj} mise(s) à jour.")
                st.rerun()

    st.markdown("#### Vue groupée")
    st.caption(
        "Une carte par attribution (point de vente × compte × code analytique), avec tous ses "
        "départements empilés verticalement — pour repérer d'un coup d'œil un doublon ou une "
        "faute de frappe (⚠️, département introuvable dans « Départements LightSpeed »). Pour "
        "les départements jamais attribués nulle part, voir la colonne « Attribution analytique » "
        "de l'onglet « Départements LightSpeed »."
    )
    groupes: dict[tuple[str, str, str, str], list[str]] = {}
    for a in mappings.get("comptes_analytiques", []):
        cle = (a.get("point_de_vente", ""), a.get("compte", ""), a.get("code_analytique", ""), a.get("famille", ""))
        groupes.setdefault(cle, []).append(a.get("categorie_lightspeed", ""))

    if not groupes:
        st.info("Aucune attribution enregistrée pour l'instant.")
    else:
        departements_connus = {d.strip().casefold() for d in departements_options}
        for (pdv, compte, code, famille), deps in sorted(groupes.items()):
            compte_affiche = _affichage_depuis_code(
                compte, mappings.get("comptes_de_vente", []), "compte", "libelle_compte"
            )
            code_affiche = _affichage_depuis_code(
                code, mappings.get("codes_analytiques", []), "code_analytique", "description"
            )
            with st.container(border=True):
                st.markdown(f"**{pdv or '—'}** · {compte_affiche or '—'} → **{code_affiche or '—'}** *(famille : {famille or '—'})*")
                lignes_dep = []
                for d in sorted(deps, key=str.casefold):
                    if d.strip().casefold() not in departements_connus:
                        lignes_dep.append(f"- ⚠️ {d} *(introuvable dans « Départements LightSpeed » — faute de frappe ?)*")
                    else:
                        lignes_dep.append(f"- {d}")
                st.markdown("\n".join(lignes_dep))

    with st.expander("🔧 Voir/éditer le détail ligne par ligne"):
        attribution_source = [
            {
                **a,
                "compte": _affichage_depuis_code(
                    a.get("compte", ""), mappings.get("comptes_de_vente", []), "compte", "libelle_compte"
                ),
                "code_analytique": _affichage_depuis_code(
                    a.get("code_analytique", ""), mappings.get("codes_analytiques", []), "code_analytique", "description"
                ),
            }
            for a in mappings.get("comptes_analytiques", [])
        ]
        edited_attribution_df = st.data_editor(
            _as_editable_df(
                attribution_source,
                ["compte", "point_de_vente", "categorie_lightspeed", "famille", "code_analytique", "commentaires"],
                tri=["point_de_vente", "categorie_lightspeed", "compte"],
            ),
            num_rows="dynamic",
            use_container_width=True,
            key="editor_attribution",
            column_config={
                "compte": st.column_config.SelectboxColumn("Compte comptable", options=comptes_options, required=True),
                "point_de_vente": st.column_config.SelectboxColumn(
                    "Point de vente", options=pdv_options, required=True
                ),
                "categorie_lightspeed": st.column_config.SelectboxColumn(
                    "Département LightSpeed", options=departements_options, required=True
                ),
                "famille": st.column_config.TextColumn("Famille analytique", required=True),
                "code_analytique": st.column_config.SelectboxColumn(
                    "Code analytique", options=codes_analytiques_options, required=True
                ),
                "commentaires": st.column_config.TextColumn("Commentaires"),
            },
        )
    edited_attribution = [
        {
            **a,
            "compte": _code_depuis_affichage(a.get("compte", "")),
            "code_analytique": _code_depuis_affichage(a.get("code_analytique", "")),
        }
        for a in edited_attribution_df.dropna(how="all").fillna("").to_dict("records")
    ]

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
            "codes_analytiques": edited_codes_analytiques,
            "comptes_analytiques": edited_attribution,
            "comptes_paiement": edited_paiement,
            "modes_paiement_ignores": edited_paiement_ignores,
            "comptes_tva": edited_tva,
        },
    )
    st.session_state.pop("resultats", None)
    st.success("Tables de correspondance enregistrées.")

if b2.button("🗑️ Vider ce référentiel"):
    reset_to_empty(client_id)
    st.session_state.pop("resultats", None)
    st.rerun()
