"""
Tests de bout en bout du pipeline LightSpeed -> Pennylane, basés sur les
scénarios décrits dans les fichiers d'exemple fournis (catégories, taux de
TVA, modes de paiement, report de la veille).

Lancer avec : python -m pytest tests/ -q
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook

from core.converter import convert
from core.lightspeed_parser import parse_lightspeed_export
from core.mapping_store import DEFAULT_MAPPINGS


def _build_sample_xlsx() -> bytes:
    """Reconstruit un export LightSpeed minimal au même format que l'export réel."""
    wb = Workbook()
    ws = wb.active
    rows = [
        ["Références comptables", "Quantité", "Total", "Rabais", "Total TTC Moins les rabais",
         "Montant taxé", "TVA 10%", "Montant taxé", "TVA 20%", "Total taxes", "%", "Total HT"],
        ["Alcool (200)", 2, 15, None, 15, None, None, 15, 2.5, 2.5, 5.7, 12.5],
        ["Cuisine - Dessert", None, None, None, None, None, None, None, None, None, None, None],
        ["Cuisine - Entrée", 10, 17, None, 17, 17, 1.5455, None, None, 1.5455, 6.5, 15.4545],
        ["Cuisine - Plat", 8, 94.6, None, 94.6, 94.6, 8.6, None, None, 8.6, 36, 86],
        ["Softs", 4, 11, None, 11, 11, 1, None, None, 1, 4.2, 10],
        ["Vin et Champagne", 6, 125, None, 125, None, None, 125, 20.8333, 20.8333, 47.6, 104.1667],
        ["Total EUR", 30, 262.6, None, 262.6, 122.6, 11.1455, 140, 23.3333, 34.4788, 100, 228.1212],
        [None] * 12,
        ["Modes de paiement", "Montant (Moins retour)"] + [None] * 10,
        ["Carte bleue", 192.6] + [None] * 10,
        ["Espèces", 98] + [None] * 10,
        ["Total des paiements", 290.6] + [None] * 10,
        ["Total des reports", -28] + [None] * 10,
        ["Report du jour d'avant", -28] + [None] * 10,
        ["Total EUR", 262.6] + [None] * 10,
        ["Total taxes EUR", 34.4788] + [None] * 10,
        ["Total EUR (Moins les taxes)", 228.1212] + [None] * 10,
    ]
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_categories_and_totals():
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    assert len(export.categories) == 5  # "Cuisine - Dessert" (vide) est ignorée
    assert export.ca_ht == 228.12
    assert export.tva_totale == 34.48
    assert export.total_paiements == 290.6
    assert export.total_reports == -28.0


def test_convert_balances_and_preserves_ca():
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    res = convert(
        export,
        DEFAULT_MAPPINGS,
        point_de_vente="REST",
        date_piece="26/05/26",
        numero_piece="LS-TEST",
    )
    assert res.sans_erreur
    assert res.ca_ok
    assert res.equilibre_ok
    assert res.ca_ht_source == res.ca_ht_genere == 228.12
    assert res.total_debit == res.total_credit == 290.6
    # Le code analytique REST est porté par la colonne Catégorie (pas de
    # colonne "Code analytique" dédiée dans le fichier Pennylane généré).
    ventes = [l for l in res.lignes if l["Crédit"] and l["Catégorie"]]
    assert ventes
    assert all(l["Catégorie"] == "REST" for l in ventes)
    assert "Code analytique" not in res.lignes[0]


def test_code_pays_uniquement_sur_comptes_classe_6_ou_7():
    """Le code pays du compte ne doit être renseigné que pour les comptes de
    charges (6) ou de produits (7) - vide pour tous les autres (TVA, tiers,
    banque/caisse, compte d'écart...)."""
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    res = convert(export, DEFAULT_MAPPINGS, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")
    assert res.sans_erreur, res.erreurs

    lignes_vente = [l for l in res.lignes if l["Numéro de compte"].startswith(("6", "7"))]
    lignes_autres = [l for l in res.lignes if not l["Numéro de compte"].startswith(("6", "7"))]

    assert lignes_vente  # au moins les comptes de vente (70110010/70110200) et la TVA le cas échéant
    assert all(l["Code pays du compte"] == "FR" for l in lignes_vente)
    assert lignes_autres  # au moins la TVA collectée (445xxx) et les paiements (511100/530000)
    assert all(l["Code pays du compte"] == "" for l in lignes_autres)


_SAMPLE_CSV_AVEC_LIGNE_TECHNIQUE = (
    "Références comptables;Quantité;Total;Rabais;;Montant taxé;TVA 10%;Total taxes;%;Total HT\r\n"
    "Cuisine - Entrée;1;11.0;;11.0;11.0;1.0;1.0;100.0;10.0\r\n"
    "Total EUR;1;11.0;;11.0;11.0;1.0;1.0;100.0;10.0\r\n"
    ";;;;;;;;;\r\n"
    "Modes de paiement;Montant (Moins retour);;;;;;;;\r\n"
    "Carte bleue;11.0;;;;;;;;\r\n"
    "Ligne technique;5.0;;;;;;;;\r\n"
    "Total EUR;11.0;;;;;;;;\r\n"
    "Total taxes EUR;1.0;;;;;;;;\r\n"
    "Total EUR (Moins les taxes);10.0;;;;;;;;"
).encode("utf-8")


def test_mode_paiement_ignore_exclu_sans_generer_de_ligne():
    """Un mode de paiement listé dans « Modes de paiement ignorés » ne doit
    générer aucune ligne (ni débit ni crédit), contrairement à un mode non
    mappé qui bloquerait l'export - mais reste signalé en avertissement."""
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_LIGNE_TECHNIQUE, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "departements": [{"categorie_lightspeed": "Cuisine - Entrée", "compte": "70110010", "taux_tva": "10%"}],
        "comptes_analytiques": [
            {"compte": "70110010", "point_de_vente": "REST", "categorie_lightspeed": "Cuisine - Entrée", "code_analytique": "REST"}
        ],
        "modes_paiement_ignores": [{"mode_paiement": "Ligne technique", "commentaires": "Test"}],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")

    assert res.sans_erreur, res.erreurs
    assert res.ca_ok
    assert res.equilibre_ok
    assert not any("Ligne technique" in l["Libellé de ligne"] for l in res.lignes)
    assert any("Ligne technique" in a and "ignoré" in a for a in res.avertissements)


def test_mode_paiement_ignore_correspondance_exacte_uniquement():
    """La correspondance est exacte : un intitulé proche mais différent n'est
    pas ignoré, il reste soumis au mapping normal (et bloque s'il est absent)."""
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_LIGNE_TECHNIQUE, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "departements": [{"categorie_lightspeed": "Cuisine - Entrée", "compte": "70110010", "taux_tva": "10%"}],
        "comptes_analytiques": [
            {"compte": "70110010", "point_de_vente": "REST", "categorie_lightspeed": "Cuisine - Entrée", "code_analytique": "REST"}
        ],
        "modes_paiement_ignores": [{"mode_paiement": "Ligne", "commentaires": "Ne doit pas matcher"}],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")
    assert not res.sans_erreur
    assert any("Ligne technique" in e and "non mappé" in e for e in res.erreurs)


def test_missing_mapping_reports_error_and_ca_mismatch():
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    mappings = {**DEFAULT_MAPPINGS, "departements": []}
    res = convert(export, mappings, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")
    assert not res.ca_ok
    assert any("non mappée" in a for a in res.avertissements)


def test_departement_sans_compte_bloque_export():
    """Un département connu mais dont le compte de vente n'a pas encore été
    choisi (paramétrage en cours) doit bloquer, pas être traité comme un
    département totalement inconnu ni pire, silencieusement ignoré."""
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    mappings = {
        **DEFAULT_MAPPINGS,
        "departements": [
            {"categorie_lightspeed": "Alcool (200)", "compte": "", "taux_tva": "20%"},
            {"categorie_lightspeed": "Cuisine - Entrée", "compte": "", "taux_tva": "10%"},
            {"categorie_lightspeed": "Cuisine - Plat", "compte": "", "taux_tva": "10%"},
            {"categorie_lightspeed": "Softs", "compte": "", "taux_tva": "10%"},
            {"categorie_lightspeed": "Vin et Champagne", "compte": "", "taux_tva": "20%"},
        ],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")
    assert not res.sans_erreur
    assert any("sans compte de vente" in e for e in res.erreurs)


def test_unknown_point_de_vente_blocks_export():
    """Le code analytique est la finalité de l'outil : un point de vente sans
    correspondance dans la table analytique doit bloquer l'export, pas juste avertir."""
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    res = convert(export, DEFAULT_MAPPINGS, point_de_vente="INCONNU", date_piece="26/05/26", numero_piece="LS-TEST")
    assert not res.sans_erreur
    assert any("code analytique" in e for e in res.erreurs)


# --- Variante CSV réelle : nombre de taux de TVA variable (5.5/10/20%), pas de
#     ligne "Total des paiements" distincte, pas de report. ------------------

_SAMPLE_CSV_3_TAUX = (
    "Références comptables;Quantité;Total;Rabais;;Montant taxé;TVA 10%;Montant taxé;TVA 20%;"
    "Montant taxé;TVA 5.5%;Total taxes;%;Total HT\r\n"
    "Alcool;32.0;445.0;0.6;444.4;;;444.4;74.0667;;;74.0667;8.2;370.3333\r\n"
    "Boisson à emporter;1.0;3.5;;3.5;;;;;3.5;0.1825;0.1825;0.1;3.3175\r\n"
    "Boissons;111.0;894.5;0.45;894.05;894.05;81.2773;;;;;81.2773;16.5;812.7727\r\n"
    "Total EUR;144.0;1343.0;1.05;1341.95;894.05;81.2773;444.4;74.0667;3.5;0.1825;155.4265;100.0;1186.5235\r\n"
    ";;;;;;;;;;;;;\r\n"
    "Modes de paiement;Montant (Moins retour);;;;;;;;;;;;\r\n"
    "Carte bleue;1000.0;;;;;;;;;;;;\r\n"
    "Espèces;341.95;;;;;;;;;;;;\r\n"
    "Total EUR;1341.95;;;;;;;;;;;;\r\n"
    "Total taxes EUR;155.4265;;;;;;;;;;;;\r\n"
    "Total EUR (Moins les taxes);1186.5235;;;;;;;;;;;;"
).encode("utf-8")


def test_parse_csv_with_variable_number_of_vat_columns():
    export = parse_lightspeed_export(_SAMPLE_CSV_3_TAUX, "export.csv")
    assert set(export.taux_tva_detectes) == {"10%", "20%", "5.5%"}
    assert len(export.categories) == 3
    taux_par_categorie = {c.libelle: c.taux_tva for c in export.categories}
    assert taux_par_categorie == {"Alcool": "20%", "Boisson à emporter": "5.5%", "Boissons": "10%"}
    assert export.ca_ht == 1186.42
    assert export.tva_totale == 155.53


def test_parse_csv_without_distinct_total_des_paiements_line():
    """Quand il n'y a pas de report, LightSpeed n'émet parfois pas de ligne
    'Total des paiements' séparée : le total encaissements == 'Total EUR' final."""
    export = parse_lightspeed_export(_SAMPLE_CSV_3_TAUX, "export.csv")
    assert export.total_paiements == export.total_eur_final == 1341.95
    assert export.total_reports == 0.0
    assert export.ventes_encaissements_coherents


def test_convert_csv_variant_balances_and_preserves_ca():
    export = parse_lightspeed_export(_SAMPLE_CSV_3_TAUX, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "comptes_de_vente": [
            {"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"},
            {"compte": "70110055", "libelle_compte": "VENTE A EMPORTER TVA 5.5%"},
            {"compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%"},
        ],
        "departements": [
            {"categorie_lightspeed": "Alcool", "compte": "70110200", "taux_tva": "20%"},
            {"categorie_lightspeed": "Boisson à emporter", "compte": "70110055", "taux_tva": "5.5%"},
            {"categorie_lightspeed": "Boissons", "compte": "70110010", "taux_tva": "10%"},
        ],
        "comptes_analytiques": [
            {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Alcool", "code_analytique": "REST"},
            {"compte": "70110055", "point_de_vente": "REST", "categorie_lightspeed": "Boisson à emporter", "code_analytique": "REST"},
            {"compte": "70110010", "point_de_vente": "REST", "categorie_lightspeed": "Boissons", "code_analytique": "REST"},
        ],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="01/06/26", numero_piece="LS-TEST-CSV")
    assert res.sans_erreur, res.erreurs
    assert res.ca_ok
    assert res.equilibre_ok
    assert res.ca_ht_source == res.ca_ht_genere == 1186.42
    # Trois comptes de TVA distincts doivent apparaître (5.5 / 10 / 20 %)
    comptes_tva_generes = {l["Numéro de compte"] for l in res.lignes if "TVA collectée" in l["Libellé de ligne"]}
    assert comptes_tva_generes == {"445710", "445711", "445712"}


# --- Variante avec pourboires : LightSpeed ajoute "Pourboire" et "Montant
#     (Moins les pourboires)", et déplace TOUS les totaux agrégés dans cette
#     dernière colonne plutôt que "Montant (Moins retour)" (la brute). Les
#     pourboires doivent être exclus des montants comptabilisés. ------------

_SAMPLE_CSV_AVEC_POURBOIRES = (
    "Références comptables;Quantité;Total;Rabais;;Montant taxé;TVA 20%;Total taxes;%;Total HT\r\n"
    "Plat;1;100.0;;100.0;100.0;16.6667;16.6667;100.0;83.3333\r\n"
    "Total EUR;1;100.0;;100.0;100.0;16.6667;16.6667;100.0;83.3333\r\n"
    ";;;;;;;;;\r\n"
    "Modes de paiement;Montant (Moins retour);Pourboire;Montant (Moins les pourboires);;;;;;\r\n"
    "ESPECES;50.0;0.0;50.0;;;;;;\r\n"
    "VISA MASTERCARD;60.0;10.0;50.0;;;;;;\r\n"
    "Total des paiements;;;100.0;;;;;;\r\n"
    "Total EUR;;;100.0;;;;;;\r\n"
    "Total taxes EUR;;;16.6667;;;;;;\r\n"
    "Total EUR (Moins les taxes);;;83.3333;;;;;;"
).encode("utf-8")


def test_parse_conserve_le_brut_et_expose_le_pourboire_par_ligne():
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    # 60€ bruts sur la carte, dont 10€ de pourboire -> le montant de la ligne reste 60€
    # (brut, conservé dans l'écriture), le pourboire est exposé à part pour sa propre
    # ligne de crédit (cf. core.converter) - jamais silencieusement absorbé.
    montants = {p.libelle: p.montant for p in export.paiements}
    pourboires = {p.libelle: p.pourboire for p in export.paiements}
    assert montants == {"ESPECES": 50.0, "VISA MASTERCARD": 60.0}
    assert pourboires == {"ESPECES": 0.0, "VISA MASTERCARD": 10.0}
    # Les totaux agrégés, eux, restent nets des pourboires (cohérents avec le CA TTC des
    # ventes déclaré par LightSpeed, qui n'a jamais inclus les pourboires) - sert au
    # contrôle de cohérence ventes/encaissements affiché à l'écran, indépendant de
    # l'écriture générée par convert().
    assert export.total_paiements == 100.0
    assert export.total_eur_final == 83.33 + 16.67  # == 100.0, cohérent avec les ventes TTC
    assert export.ca_ttc == 100.0
    assert export.ventes_encaissements_coherents


def test_convert_pourboire_credite_le_compte_dedie_sans_tva():
    """Le montant brut encaissé (pourboire compris) reste au débit du compte de
    contrepartie ; le pourboire génère en parallèle une ligne de crédit dédiée sur le
    compte de pourboires du mode de paiement concerné, sans aucune TVA - l'écriture doit
    s'équilibrer exactement, brut au débit contre (ventes + TVA + pourboire) au crédit."""
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "comptes_de_vente": [{"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"}],
        "departements": [{"categorie_lightspeed": "Plat", "compte": "70110200", "taux_tva": "20%"}],
        "comptes_analytiques": [
            {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Plat", "code_analytique": "REST"}
        ],
        "comptes_paiement": [
            {"mode_paiement": "ESPECES", "compte": "530000", "libelle_compte": "Caisse"},
            {"mode_paiement": "VISA MASTERCARD", "compte": "511100", "libelle_compte": "Remises CB"},
        ],
        "comptes_pourboires": [
            {"point_de_vente": "REST", "mode_paiement": "VISA MASTERCARD", "compte": "462200", "libelle_compte": "Pourboires à reverser - CB"},
        ],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="11/08/26", numero_piece="LS-TEST")
    assert res.sans_erreur, res.erreurs
    assert res.equilibre_ok
    assert res.ecart_calcule == 0.0
    assert not res.avertissements
    assert res.total_debit == res.total_credit == 110.0  # brut : 50 espèces + 60 carte

    ligne_carte = next(l for l in res.lignes if l["Libellé de ligne"] == "VISA MASTERCARD")
    assert ligne_carte["Débit et/ou Crédit"] == 60.0  # brut, pourboire compris

    ligne_pourboire = next(l for l in res.lignes if l["Libellé de ligne"] == "Pourboire VISA MASTERCARD")
    assert ligne_pourboire["Numéro de compte"] == "462200"
    assert ligne_pourboire["Crédit"] == 10.0
    assert ligne_pourboire["Taux de TVA du compte"] == ""  # jamais de TVA sur un pourboire
    assert ligne_pourboire["Catégorie"] == ""

    # ESPECES n'a pas de pourboire sur cet export : aucune ligne "Pourboire ESPECES" générée.
    assert not any(l["Libellé de ligne"] == "Pourboire ESPECES" for l in res.lignes)


def test_convert_pourboire_sans_compte_mappe_bloque_l_export():
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "comptes_de_vente": [{"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"}],
        "departements": [{"categorie_lightspeed": "Plat", "compte": "70110200", "taux_tva": "20%"}],
        "comptes_analytiques": [
            {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Plat", "code_analytique": "REST"}
        ],
        "comptes_paiement": [
            {"mode_paiement": "ESPECES", "compte": "530000", "libelle_compte": "Caisse"},
            {"mode_paiement": "VISA MASTERCARD", "compte": "511100", "libelle_compte": "Remises CB"},
        ],
        "comptes_pourboires": [],  # aucun compte de pourboire paramétré
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="11/08/26", numero_piece="LS-TEST")
    assert not res.sans_erreur
    assert any("Pourboire" in e and "VISA MASTERCARD" in e for e in res.erreurs)
    assert not any(l["Libellé de ligne"] == "Pourboire VISA MASTERCARD" for l in res.lignes)


def test_convert_pourboire_compte_different_selon_le_point_de_vente():
    # Reproduit le cas rapporté : un même mode de paiement (VISA MASTERCARD) doit créditer un
    # compte différent selon le point de vente d'origine (REST vs BARF) - sans le point de vente
    # comme critère, la première ligne du référentiel gagnerait toujours, quel que soit le point
    # de vente réellement concerné.
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    mappings_communs = {
        "comptes_de_vente": [{"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"}],
        "departements": [{"categorie_lightspeed": "Plat", "compte": "70110200", "taux_tva": "20%"}],
        "comptes_paiement": [
            {"mode_paiement": "ESPECES", "compte": "530000", "libelle_compte": "Caisse"},
            {"mode_paiement": "VISA MASTERCARD", "compte": "511100", "libelle_compte": "Remises CB"},
        ],
        "comptes_pourboires": [
            {"point_de_vente": "REST", "mode_paiement": "VISA MASTERCARD", "compte": "462200", "libelle_compte": "Pourboires CB - Restaurant"},
            {"point_de_vente": "BARF", "mode_paiement": "VISA MASTERCARD", "compte": "462201", "libelle_compte": "Pourboires CB - Bar"},
        ],
    }

    res_rest = convert(
        export,
        {
            **DEFAULT_MAPPINGS,
            **mappings_communs,
            "comptes_analytiques": [
                {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Plat", "code_analytique": "REST"}
            ],
        },
        point_de_vente="REST",
        date_piece="11/08/26",
        numero_piece="LS-TEST-REST",
    )
    assert res_rest.sans_erreur, res_rest.erreurs
    ligne_rest = next(l for l in res_rest.lignes if l["Libellé de ligne"] == "Pourboire VISA MASTERCARD")
    assert ligne_rest["Numéro de compte"] == "462200"

    res_bar = convert(
        export,
        {
            **DEFAULT_MAPPINGS,
            **mappings_communs,
            "comptes_analytiques": [
                {"compte": "70110200", "point_de_vente": "BARF", "categorie_lightspeed": "Plat", "code_analytique": "BARF"}
            ],
        },
        point_de_vente="BARF",
        date_piece="11/08/26",
        numero_piece="LS-TEST-BARF",
    )
    assert res_bar.sans_erreur, res_bar.erreurs
    ligne_bar = next(l for l in res_bar.lignes if l["Libellé de ligne"] == "Pourboire VISA MASTERCARD")
    assert ligne_bar["Numéro de compte"] == "462201"


def test_convert_compte_paiement_ligne_tous_sert_a_tout_point_de_vente_sans_ligne_dediee():
    # Reproduit le cas rapporté : ESPECES doit créditer un compte différent selon le point de
    # vente (REST vs BARF), alors que VISA MASTERCARD n'a qu'une ligne "TOUS" (comme la grande
    # majorité des moyens de paiement) et doit donc utiliser ce même compte quel que soit le
    # point de vente concerné.
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    mappings_communs = {
        "comptes_de_vente": [{"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"}],
        "departements": [{"categorie_lightspeed": "Plat", "compte": "70110200", "taux_tva": "20%"}],
        "comptes_paiement": [
            {"point_de_vente": "TOUS", "mode_paiement": "VISA MASTERCARD", "compte": "511100", "libelle_compte": "Remises CB"},
            {"point_de_vente": "REST", "mode_paiement": "ESPECES", "compte": "530000", "libelle_compte": "Caisse - Restaurant"},
            {"point_de_vente": "BARF", "mode_paiement": "ESPECES", "compte": "530001", "libelle_compte": "Caisse - Bar"},
        ],
        "comptes_pourboires": [
            {"point_de_vente": "REST", "mode_paiement": "VISA MASTERCARD", "compte": "462200", "libelle_compte": "Pourboires CB"},
            {"point_de_vente": "BARF", "mode_paiement": "VISA MASTERCARD", "compte": "462200", "libelle_compte": "Pourboires CB"},
        ],
    }

    res_rest = convert(
        export,
        {
            **DEFAULT_MAPPINGS,
            **mappings_communs,
            "comptes_analytiques": [
                {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Plat", "code_analytique": "REST"}
            ],
        },
        point_de_vente="REST",
        date_piece="11/08/26",
        numero_piece="LS-TEST-REST",
    )
    assert res_rest.sans_erreur, res_rest.erreurs
    assert next(l for l in res_rest.lignes if l["Libellé de ligne"] == "ESPECES")["Numéro de compte"] == "530000"
    # VISA MASTERCARD retombe sur la ligne "TOUS" (pas de ligne "REST" dédiée) : même compte
    # que pour BARF ci-dessous.
    assert next(l for l in res_rest.lignes if l["Libellé de ligne"] == "VISA MASTERCARD")["Numéro de compte"] == "511100"

    res_bar = convert(
        export,
        {
            **DEFAULT_MAPPINGS,
            **mappings_communs,
            "comptes_analytiques": [
                {"compte": "70110200", "point_de_vente": "BARF", "categorie_lightspeed": "Plat", "code_analytique": "BARF"}
            ],
        },
        point_de_vente="BARF",
        date_piece="11/08/26",
        numero_piece="LS-TEST-BARF",
    )
    assert res_bar.sans_erreur, res_bar.erreurs
    assert next(l for l in res_bar.lignes if l["Libellé de ligne"] == "ESPECES")["Numéro de compte"] == "530001"
    assert next(l for l in res_bar.lignes if l["Libellé de ligne"] == "VISA MASTERCARD")["Numéro de compte"] == "511100"


def test_convert_compte_paiement_sans_point_de_vente_traite_comme_tous():
    # Compatibilité ascendante : une ligne sans "point_de_vente" du tout (référentiel d'une
    # version antérieure à cette colonne) doit continuer à s'appliquer à tout point de vente,
    # exactement comme une ligne "TOUS" explicite.
    export = parse_lightspeed_export(_SAMPLE_CSV_AVEC_POURBOIRES, "export.csv")
    mappings = {
        **DEFAULT_MAPPINGS,
        "comptes_de_vente": [{"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"}],
        "departements": [{"categorie_lightspeed": "Plat", "compte": "70110200", "taux_tva": "20%"}],
        "comptes_analytiques": [
            {"compte": "70110200", "point_de_vente": "REST", "categorie_lightspeed": "Plat", "code_analytique": "REST"}
        ],
        "comptes_paiement": [
            {"mode_paiement": "ESPECES", "compte": "530000", "libelle_compte": "Caisse"},  # pas de point_de_vente
            {"mode_paiement": "VISA MASTERCARD", "compte": "511100", "libelle_compte": "Remises CB"},
        ],
        "comptes_pourboires": [
            {"point_de_vente": "REST", "mode_paiement": "VISA MASTERCARD", "compte": "462200", "libelle_compte": "Pourboires CB"},
        ],
    }
    res = convert(export, mappings, point_de_vente="REST", date_piece="11/08/26", numero_piece="LS-TEST")
    assert res.sans_erreur, res.erreurs
    assert next(l for l in res.lignes if l["Libellé de ligne"] == "ESPECES")["Numéro de compte"] == "530000"
