"""Tests de core.mapping_store : export global .xlsx (un onglet par table)."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl

from core.mapping_store import EMPTY_MAPPINGS, build_export_global_xlsx


def test_build_export_global_xlsx_un_onglet_par_table():
    mappings = {
        **EMPTY_MAPPINGS,
        "points_de_vente": [{"code": "REST", "libelle": "Restaurant", "adresse_email": "", "adresse_resultat": "", "commentaires": ""}],
        "comptes_de_vente": [{"compte": "70110010", "libelle_compte": "Ventes", "commentaires": ""}],
    }
    contenu = build_export_global_xlsx(mappings)
    wb = openpyxl.load_workbook(io.BytesIO(contenu))

    assert wb.sheetnames == [
        "Points de vente",
        "Comptes de vente PL",
        "Codes Analytique PL",
        "Départements LS",
        "Moyens de paiements",
        "Moyens paiement ignorés",
        "Taux de TVA",
        "Attribution analytique",
    ]
    ws = wb["Points de vente"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("code", "libelle", "adresse_email", "adresse_resultat", "commentaires")
    assert rows[1][:2] == ("REST", "Restaurant")


def test_build_export_global_xlsx_tables_vides_gardent_les_colonnes():
    contenu = build_export_global_xlsx(EMPTY_MAPPINGS)
    wb = openpyxl.load_workbook(io.BytesIO(contenu))
    ws = wb["Taux de TVA"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows == [("taux", "compte", "libelle_compte", "commentaires")]  # en-tête seul, table vide
