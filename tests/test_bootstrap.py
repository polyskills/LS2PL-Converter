"""
Vérifie que les clients et points de vente par défaut (Paris/Valence,
Restaurant/Bar) sont recréés de façon idempotente et sans jamais écraser
une personnalisation existante — condition nécessaire pour survivre à un
redémarrage Streamlit Cloud (disque non persistant).
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.bootstrap import DEFAULT_CLIENTS, DEFAULT_POINTS_DE_VENTE, ensure_defaults
from core.client_store import CLIENTS_DIR, list_clients
from core.mapping_store import load_mappings, save_mappings


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def test_ensure_defaults_creates_expected_clients_and_points_de_vente():
    ensure_defaults()
    ids = {c["id"] for c in list_clients()}
    assert ids == {c["id"] for c in DEFAULT_CLIENTS}

    for c in DEFAULT_CLIENTS:
        codes = {p["code"] for p in load_mappings(c["id"])["points_de_vente"]}
        assert codes == {p["code"] for p in DEFAULT_POINTS_DE_VENTE}


def test_ensure_defaults_is_idempotent_and_preserves_customizations():
    ensure_defaults()

    # L'utilisateur personnalise le référentiel de "paris" : compte de vente
    # additionnel + point de vente supplémentaire.
    mappings = load_mappings("paris")
    mappings["comptes_ventes"].append(
        {"categorie_lightspeed": "Test", "compte": "70100000", "libelle_compte": "Test", "taux_tva": "10%"}
    )
    mappings["points_de_vente"].append({"code": "TERRASSE", "libelle": "TERRASSE"})
    save_mappings("paris", mappings)

    # Simule un redémarrage : le bootstrap est rejoué plusieurs fois.
    ensure_defaults()
    ensure_defaults()

    assert len(list_clients()) == len(DEFAULT_CLIENTS)  # pas de doublon de client

    mappings_apres = load_mappings("paris")
    codes = [p["code"] for p in mappings_apres["points_de_vente"]]
    assert codes.count("RESTAURANT") == 1
    assert codes.count("BAR") == 1
    assert "TERRASSE" in codes  # la personnalisation n'a pas été perdue
    assert len(mappings_apres["comptes_ventes"]) == 1  # ni écrasée
