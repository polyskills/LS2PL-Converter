"""
Vérifie que les clients, points de vente et référentiel de départ (Paris/
Valence, Restaurant/Bar, comptes de vente/départements/paiement/TVA connus
du client Paris) sont recréés de façon idempotente et sans jamais écraser
une personnalisation existante — condition nécessaire pour survivre à un
redémarrage Streamlit Cloud (disque non persistant).
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.bootstrap import (
    DEFAULT_CLIENTS,
    DEFAULT_CODES_ANALYTIQUES,
    DEFAULT_COMPTES_DE_VENTE,
    DEFAULT_COMPTES_PAIEMENT,
    DEFAULT_COMPTES_TVA,
    DEFAULT_DEPARTEMENTS,
    DEFAULT_POINTS_DE_VENTE,
    ensure_defaults,
)
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


def test_ensure_defaults_seeds_paris_referentiel():
    ensure_defaults()
    mappings = load_mappings("paris")

    comptes = {c["compte"] for c in mappings["comptes_de_vente"]}
    assert comptes == {c["compte"] for c in DEFAULT_COMPTES_DE_VENTE["paris"]}

    departements = {d["categorie_lightspeed"] for d in mappings["departements"]}
    assert departements == {d["categorie_lightspeed"] for d in DEFAULT_DEPARTEMENTS["paris"]}

    codes_analytiques = {c["code_analytique"] for c in mappings["codes_analytiques"]}
    assert codes_analytiques == {c["code_analytique"] for c in DEFAULT_CODES_ANALYTIQUES["paris"]}

    modes_paiement = {p["mode_paiement"] for p in mappings["comptes_paiement"]}
    assert modes_paiement == {p["mode_paiement"] for p in DEFAULT_COMPTES_PAIEMENT["paris"]}

    taux_tva = {t["taux"] for t in mappings["comptes_tva"]}
    assert taux_tva == {t["taux"] for t in DEFAULT_COMPTES_TVA["paris"]}

    # Valence n'a pas encore de référentiel confirmé : rien n'est inventé pour ce client.
    mappings_valence = load_mappings("valence")
    assert mappings_valence["comptes_de_vente"] == []
    assert mappings_valence["departements"] == []
    assert mappings_valence["codes_analytiques"] == []


def test_ensure_defaults_is_idempotent_and_preserves_customizations():
    ensure_defaults()

    # L'utilisateur personnalise le référentiel de "paris" : département
    # additionnel (avec compte renseigné) + point de vente supplémentaire.
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
    assert codes.count("RESTAURANT") == 1
    assert codes.count("BAR") == 1
    assert "TERRASSE" in codes  # la personnalisation n'a pas été perdue

    departements_apres = [d["categorie_lightspeed"] for d in mappings_apres["departements"]]
    assert departements_apres.count("Test") == 1  # ni dupliquée
    assert len(mappings_apres["departements"]) == len(DEFAULT_DEPARTEMENTS["paris"]) + 1  # ni écrasée


def test_ensure_defaults_does_not_resurrect_deleted_default_rows():
    """Bug constaté : une ligne du référentiel de départ (ex. un mode de
    paiement) supprimée puis enregistrée depuis l'interface réapparaissait au
    rechargement suivant, car ensure_defaults() est rejoué à chaque rendu de
    page (pas seulement au démarrage) et ne distinguait pas "jamais existé"
    de "supprimée volontairement". Le seed ne doit s'appliquer qu'une fois."""
    ensure_defaults()

    mappings = load_mappings("paris")
    avant = len(mappings["comptes_paiement"])
    assert avant == len(DEFAULT_COMPTES_PAIEMENT["paris"])

    # L'utilisateur supprime tous les modes de paiement pré-remplis et enregistre.
    mappings["comptes_paiement"] = []
    save_mappings("paris", mappings)

    # Rechargements successifs de la page (chacun rejoue ensure_defaults()).
    ensure_defaults()
    ensure_defaults()

    assert load_mappings("paris")["comptes_paiement"] == []
