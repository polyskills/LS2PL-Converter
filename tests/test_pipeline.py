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
    # Toutes les lignes de vente portent le code analytique REST
    ventes = [l for l in res.lignes if l["Crédit"] and l["Code analytique"]]
    assert all(l["Code analytique"] == "REST" for l in ventes)


def test_missing_mapping_reports_error_and_ca_mismatch():
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    mappings = {**DEFAULT_MAPPINGS, "comptes_ventes": []}
    res = convert(export, mappings, point_de_vente="REST", date_piece="26/05/26", numero_piece="LS-TEST")
    assert not res.ca_ok
    assert any("non mappée" in a for a in res.avertissements)


def test_unknown_point_de_vente_flags_warning_without_blocking():
    export = parse_lightspeed_export(_build_sample_xlsx(), "test_export.xlsx")
    res = convert(export, DEFAULT_MAPPINGS, point_de_vente="INCONNU", date_piece="26/05/26", numero_piece="LS-TEST")
    assert res.ca_ok  # le CA est quand même généré...
    assert any("code analytique" in a for a in res.avertissements)  # ...mais sans code analytique


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
        "comptes_ventes": [
            {"categorie_lightspeed": "Alcool", "compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%", "taux_tva": "20%"},
            {"categorie_lightspeed": "Boisson à emporter", "compte": "70110055", "libelle_compte": "VENTE A EMPORTER TVA 5.5%", "taux_tva": "5.5%"},
            {"categorie_lightspeed": "Boissons", "compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%", "taux_tva": "10%"},
        ],
        "comptes_analytiques": [
            {"compte": "70110200", "point_de_vente": "REST", "code_analytique": "REST"},
            {"compte": "70110055", "point_de_vente": "REST", "code_analytique": "REST"},
            {"compte": "70110010", "point_de_vente": "REST", "code_analytique": "REST"},
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
