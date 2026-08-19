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


def test_build_export_global_xlsx_largeur_colonnes_ajustee_au_contenu():
    mappings = {
        **EMPTY_MAPPINGS,
        "comptes_de_vente": [
            {"compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10% RESTAURANT PRINCIPAL", "commentaires": ""},
        ],
    }
    contenu = build_export_global_xlsx(mappings)
    wb = openpyxl.load_workbook(io.BytesIO(contenu))
    ws = wb["Comptes de vente PL"]

    largeur_compte = ws.column_dimensions["A"].width  # "compte" (8) vs "70110010" (8)
    largeur_libelle = ws.column_dimensions["B"].width  # "libelle_compte" (14) vs le long libellé (43)

    assert largeur_libelle > largeur_compte  # bien ajustée au contenu le plus long, pas une largeur fixe uniforme
    assert largeur_libelle < 62  # plafonnée, pas illimitée


def test_build_export_global_xlsx_largeur_plafonnee_pour_texte_tres_long():
    mappings = {
        **EMPTY_MAPPINGS,
        "comptes_de_vente": [{"compte": "1", "libelle_compte": "x", "commentaires": "y" * 500}],
    }
    contenu = build_export_global_xlsx(mappings)
    wb = openpyxl.load_workbook(io.BytesIO(contenu))
    ws = wb["Comptes de vente PL"]
    assert ws.column_dimensions["C"].width == 60  # plafond, pas 502
