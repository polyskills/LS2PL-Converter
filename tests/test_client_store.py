"""Tests de core.client_store, en particulier la suppression d'un client par
défaut (Paris/Valence) : reproduit le bug rapporté où la suppression
n'avait aucun effet visible, le client étant recréé instantanément."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.bootstrap import ensure_defaults
from core.client_store import (
    CLIENTS_DIR,
    create_client,
    delete_client,
    ensure_client,
    get_client,
    list_clients,
)


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def test_supprimer_un_client_normal_fonctionne():
    client = create_client("Test Suppression")
    delete_client(client["id"])
    assert get_client(client["id"]) is None


def test_ensure_client_ne_recree_pas_un_client_explicitement_supprime():
    # Reproduit le bug : ensure_client() est rejoué à CHAQUE rendu de page
    # (via core.bootstrap.ensure_defaults) - sans garde-fou, un client par
    # défaut supprimé réapparaissait dès le rendu suivant.
    ensure_client("paris", "Paris")
    assert get_client("paris") is not None

    delete_client("paris")
    assert get_client("paris") is None

    ensure_client("paris", "Paris")  # rejoué comme au rendu de page suivant
    assert get_client("paris") is None  # toujours supprimé, pas recréé


def test_ensure_defaults_ne_recree_pas_un_defaut_supprime():
    ensure_defaults()
    assert get_client("paris") is not None
    assert get_client("valence") is not None

    delete_client("paris")
    ensure_defaults()  # comme au rendu de page suivant (select_client())

    assert get_client("paris") is None
    assert get_client("valence") is not None  # les autres défauts, eux, restent intacts


def test_recreer_explicitement_un_client_supprime_annule_la_marque():
    # Un client normal (pas un défaut) supprimé puis recréé À LA MAIN (même
    # nom -> même identifiant slugifié) doit ensuite pouvoir être supprimé à
    # nouveau normalement, sans rester bloqué par l'ancienne marque.
    client = create_client("Louvre Gourmet")
    delete_client(client["id"])
    assert get_client(client["id"]) is None

    recree = create_client("Louvre Gourmet")
    assert recree["id"] == client["id"]
    assert get_client(client["id"]) is not None

    delete_client(client["id"])
    assert get_client(client["id"]) is None


def test_suppression_n_affecte_pas_les_autres_clients():
    a = create_client("Client A")
    b = create_client("Client B")
    delete_client(a["id"])
    assert get_client(a["id"]) is None
    assert get_client(b["id"]) is not None
    assert [c["id"] for c in list_clients()] == [b["id"]]
