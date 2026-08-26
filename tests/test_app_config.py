"""Tests de core.app_config : authentification basique par code d'accès unique."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.app_config import (
    APP_CONFIG_PATH,
    has_auth_password,
    is_auth_active,
    set_auth_active,
    set_auth_password,
    verifier_mot_de_passe,
)


@pytest.fixture(autouse=True)
def _clean_app_config():
    if os.path.exists(APP_CONFIG_PATH):
        os.remove(APP_CONFIG_PATH)
    yield
    if os.path.exists(APP_CONFIG_PATH):
        os.remove(APP_CONFIG_PATH)


def test_auth_desactivee_et_sans_mot_de_passe_par_defaut():
    assert is_auth_active() is False
    assert has_auth_password() is False


def test_set_auth_password_puis_verification():
    set_auth_password("secret123")
    assert has_auth_password() is True
    assert verifier_mot_de_passe("secret123") is True
    assert verifier_mot_de_passe("mauvais") is False


def test_mot_de_passe_jamais_stocke_en_clair():
    set_auth_password("secret123")
    with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
        contenu = f.read()
    assert "secret123" not in contenu


def test_verifier_mot_de_passe_sans_mot_de_passe_defini_refuse_tout():
    # Aucun code défini : même une chaîne vide ne doit jamais être acceptée.
    assert verifier_mot_de_passe("") is False
    assert verifier_mot_de_passe("nimporte quoi") is False


def test_activer_puis_desactiver_authentification():
    set_auth_active(True)
    assert is_auth_active() is True
    set_auth_active(False)
    assert is_auth_active() is False


def test_changer_le_mot_de_passe_invalide_l_ancien():
    set_auth_password("ancien")
    set_auth_password("nouveau")
    assert verifier_mot_de_passe("ancien") is False
    assert verifier_mot_de_passe("nouveau") is True
