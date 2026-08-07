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
