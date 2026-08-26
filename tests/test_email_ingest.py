"""Tests de core.email_ingest.extraire_periode : la période doit être détectée
quel que soit le préfixe du nom de fichier, tant qu'il se termine par les
deux dates AAAAMMJJ_AAAAMMJJ."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.email_ingest import date_aaaammjj, extraire_periode


def test_extraire_periode_convention_business_export_accounting():
    date_debut, date_fin = extraire_periode(
        "annesophiepicparis_ladamedepicbar_business_export_accounting_20260810_20260811.xls"
    )
    assert date_debut == "10/08/26"
    assert date_fin == "11/08/26"


def test_extraire_periode_prefixe_quelconque():
    # Reproduit le cas rapporté : un nom de fichier de test manuel, sans le
    # libellé "business_export_accounting", mais avec les deux dates en fin
    # de nom comme sur un export réel — la période doit quand même être détectée.
    date_debut, date_fin = extraire_periode("test-mail-automatique_20260826_20260827.xls")
    assert date_debut == "26/08/26"
    assert date_fin == "27/08/26"


def test_extraire_periode_sans_extension():
    date_debut, date_fin = extraire_periode("export_20260826_20260827")
    assert date_debut == "26/08/26"
    assert date_fin == "27/08/26"


def test_extraire_periode_introuvable_renvoie_none():
    date_debut, date_fin = extraire_periode("export_sans_dates.xls")
    assert date_debut is None
    assert date_fin is None


def test_extraire_periode_une_seule_date_renvoie_none():
    # Une seule date en fin de nom ne suffit pas à déterminer une période.
    date_debut, date_fin = extraire_periode("export_20260826.xls")
    assert date_debut is None
    assert date_fin is None


def test_date_aaaammjj_inverse_le_formatage_dd_mm_aa():
    # Inverse de _formate_date : reconstitue AAAAMMJJ pour un nom de fichier
    # à partir du format dd/mm/aa utilisé pour la pièce comptable.
    assert date_aaaammjj("26/08/26") == "20260826"
    assert date_aaaammjj("01/01/25") == "20250101"
