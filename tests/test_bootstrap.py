"""
Vérifie que les clients par défaut (Paris/Valence) sont recréés de façon
idempotente — condition nécessaire pour survivre à un redémarrage Streamlit
Cloud (disque non persistant) — et que leur référentiel, lui, n'est JAMAIS
peuplé automatiquement : il ne se remplit que par saisie manuelle dans
l'interface ou par restauration d'une sauvegarde.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.bootstrap import DEFAULT_CLIENTS, ensure_defaults
from core.client_store import CLIENTS_DIR, list_clients
from core.mapping_store import load_mappings, save_mappings


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def test_ensure_defaults_creates_expected_clients_with_empty_referentiel():
    ensure_defaults()
    ids = {c["id"] for c in list_clients()}
    assert ids == {c["id"] for c in DEFAULT_CLIENTS}

    for c in DEFAULT_CLIENTS:
        mappings = load_mappings(c["id"])
        assert mappings["points_de_vente"] == []
        assert mappings["comptes_de_vente"] == []
        assert mappings["departements"] == []
        assert mappings["codes_analytiques"] == []
        assert mappings["comptes_paiement"] == []
        assert mappings["comptes_tva"] == []


def test_ensure_defaults_is_idempotent_and_preserves_customizations():
    ensure_defaults()

    # L'utilisateur saisit son propre référentiel pour "paris".
    mappings = load_mappings("paris")
    mappings["departements"].append(
        {"categorie_lightspeed": "Test", "compte": "70100000", "taux_tva": "10%"}
    )
    mappings["points_de_vente"].append({"code": "TERRASSE", "libelle": "TERRASSE"})
    save_mappings("paris", mappings)

    # Simule un redémarrage : le bootstrap est rejoué plusieurs fois.
    ensure_defaults()
    ensure_defaults()

    assert len(list_clients()) == len(DEFAULT_CLIENTS)  # pas de doublon de client

    mappings_apres = load_mappings("paris")
    codes = [p["code"] for p in mappings_apres["points_de_vente"]]
    assert codes == ["TERRASSE"]  # rien d'ajouté automatiquement, rien perdu

    departements_apres = [d["categorie_lightspeed"] for d in mappings_apres["departements"]]
    assert departements_apres == ["Test"]
