"""Tests de core.client_store : création, renommage et suppression de client."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.client_store import CLIENTS_DIR, create_client, delete_client, get_client, list_clients


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def test_supprimer_un_client_fonctionne():
    client = create_client("Test Suppression")
    delete_client(client["id"])
    assert get_client(client["id"]) is None


def test_recreer_un_client_supprime_fonctionne():
    # Un client supprimé, puis recréé à la main (même nom -> même identifiant
    # slugifié), doit ensuite pouvoir être supprimé à nouveau normalement.
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
