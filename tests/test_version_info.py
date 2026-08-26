"""Tests de core.version_info."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.version_info as version_info


def test_get_version_info_contre_le_vrai_depot():
    info = version_info.get_version_info()
    assert info["hash"]
    assert info["branch"]


def test_get_version_info_force_l_encodage_utf8(monkeypatch):
    # Régression : sans encoding="utf-8" explicite, Windows décode la sortie de
    # subprocess avec la page de code par défaut (souvent CP1252, pas UTF-8),
    # produisant du mojibake sur le message du dernier commit affiché page
    # Réglages > Informations dès qu'il contient un accent.
    appels = []

    class FauxProcessus:
        stdout = "abc1234|2026-01-01T00:00:00+01:00|Message accentué : ê î"

    def faux_run(cmd, **kwargs):
        appels.append(kwargs)
        return FauxProcessus()

    monkeypatch.setattr(version_info.subprocess, "run", faux_run)
    version_info.get_version_info()

    assert all(kwargs.get("encoding") == "utf-8" for kwargs in appels)
