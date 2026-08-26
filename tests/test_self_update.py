"""
Tests de core.self_update. verifier_mise_a_jour() est testée contre le
VRAI dépôt (lecture seule : rev-parse, fetch) — sans risque. En revanche
appliquer_mise_a_jour() n'est JAMAIS testée contre le vrai dépôt : elle
fait un `git reset --hard`, potentiellement destructeur pour l'état de
travail réel. On simule donc _git() et subprocess.run() pour ne tester que
la logique (repli sur les dépendances, écriture de la sentinelle,
propagation des erreurs), sans jamais toucher au dépôt sur disque.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.self_update as self_update


def test_git_force_l_encodage_utf8(monkeypatch):
    # Régression : sans encoding="utf-8" explicite, Windows décode la sortie de
    # subprocess avec la page de code par défaut (souvent CP1252, pas UTF-8),
    # produisant du mojibake sur les messages de commit accentués ("Ãªtre" au
    # lieu de "être") alors que git restitue bien de l'UTF-8.
    appels = []

    class FauxProcessus:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def faux_run(cmd, **kwargs):
        appels.append(kwargs)
        return FauxProcessus()

    monkeypatch.setattr(self_update.subprocess, "run", faux_run)
    self_update._git("status")

    assert appels[0].get("encoding") == "utf-8"


def test_verifier_mise_a_jour_contre_le_vrai_depot():
    resultat = self_update.verifier_mise_a_jour()
    assert resultat["erreur"] is None
    assert resultat["disponible"] is True
    assert resultat["branche"]
    assert resultat["commit_local"] and len(resultat["commit_local"]) == 8
    assert resultat["a_jour"] in (True, False)


def test_verifier_mise_a_jour_hors_depot_git(tmp_path, monkeypatch):
    monkeypatch.setattr(self_update, "BASE_DIR", str(tmp_path))
    resultat = self_update.verifier_mise_a_jour()
    assert resultat["disponible"] is None
    assert resultat["erreur"]


def test_hash_fichier_detecte_un_changement(tmp_path):
    f = tmp_path / "requirements.txt"
    f.write_text("streamlit==1.0\n")
    h1 = self_update._hash_fichier(str(f))
    f.write_text("streamlit==2.0\n")
    h2 = self_update._hash_fichier(str(f))
    assert h1 != h2


def test_hash_fichier_absent_renvoie_none():
    assert self_update._hash_fichier("/chemin/totalement/inexistant.txt") is None


def _fake_git_ok(reset_modifie_requirements=None, req_path=None):
    """Fabrique un _git() simulé couvrant le déroulé nominal
    (branche -> fetch -> reset -> nouveau hash), sans jamais toucher au
    vrai dépôt."""
    def fake_git(*args, timeout=15):
        if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
            return True, "claude/lightspeed-pennylane-converter-njmeyd"
        if args[0] == "fetch":
            return True, ""
        if args[0] == "reset":
            if reset_modifie_requirements and req_path:
                req_path.write_text(reset_modifie_requirements)
            return True, ""
        if args[0] == "rev-parse" and args[1] == "--short":
            return True, "abc1234"
        return True, ""
    return fake_git


def test_appliquer_mise_a_jour_ecrit_la_sentinelle_sans_reinstaller_si_requirements_inchange(tmp_path, monkeypatch):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("streamlit==1.0\n")
    sentinel = tmp_path / "data" / ".fetch_mail_restart_requested"

    monkeypatch.setattr(self_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(self_update, "REQUIREMENTS_PATH", str(req_path))
    monkeypatch.setattr(self_update, "RESTART_SENTINEL_EMAIL_POLLER", str(sentinel))
    monkeypatch.setattr(self_update, "_git", _fake_git_ok())

    resultat = self_update.appliquer_mise_a_jour()

    assert resultat["succes"] is True
    assert resultat["nouveau_commit"] == "abc1234"
    assert resultat["dependances_reinstallees"] is False
    assert sentinel.exists()


def test_appliquer_mise_a_jour_reinstalle_les_dependances_si_requirements_change(tmp_path, monkeypatch):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("streamlit==1.0\n")
    sentinel = tmp_path / "data" / ".fetch_mail_restart_requested"

    monkeypatch.setattr(self_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(self_update, "REQUIREMENTS_PATH", str(req_path))
    monkeypatch.setattr(self_update, "RESTART_SENTINEL_EMAIL_POLLER", str(sentinel))
    monkeypatch.setattr(self_update, "_git", _fake_git_ok(reset_modifie_requirements="streamlit==2.0\n", req_path=req_path))

    class FauxProcessus:
        returncode = 0
        stderr = ""
        stdout = ""

    appels_pip = []

    def faux_run(cmd, **kwargs):
        appels_pip.append(cmd)
        return FauxProcessus()

    monkeypatch.setattr(self_update.subprocess, "run", faux_run)

    resultat = self_update.appliquer_mise_a_jour()

    assert resultat["succes"] is True
    assert resultat["dependances_reinstallees"] is True
    assert len(appels_pip) == 1
    assert "pip" in appels_pip[0]
    assert sentinel.exists()


def test_appliquer_mise_a_jour_echec_pip_ne_pose_pas_la_sentinelle(tmp_path, monkeypatch):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("streamlit==1.0\n")
    sentinel = tmp_path / "data" / ".fetch_mail_restart_requested"

    monkeypatch.setattr(self_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(self_update, "REQUIREMENTS_PATH", str(req_path))
    monkeypatch.setattr(self_update, "RESTART_SENTINEL_EMAIL_POLLER", str(sentinel))
    monkeypatch.setattr(self_update, "_git", _fake_git_ok(reset_modifie_requirements="streamlit==2.0\n", req_path=req_path))

    class FauxProcessusEchec:
        returncode = 1
        stderr = "erreur pip"
        stdout = ""

    monkeypatch.setattr(self_update.subprocess, "run", lambda cmd, **kwargs: FauxProcessusEchec())

    resultat = self_update.appliquer_mise_a_jour()

    assert resultat["succes"] is False
    assert "erreur pip" in resultat["erreur"]
    assert not sentinel.exists()  # jamais de redémarrage programmé sur un échec


def test_appliquer_mise_a_jour_echoue_proprement_si_fetch_echoue(tmp_path, monkeypatch):
    sentinel = tmp_path / "data" / ".fetch_mail_restart_requested"
    monkeypatch.setattr(self_update, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(self_update, "RESTART_SENTINEL_EMAIL_POLLER", str(sentinel))

    def fake_git(*args, timeout=15):
        if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
            return True, "main"
        if args[0] == "fetch":
            return False, "réseau indisponible"
        return True, ""

    monkeypatch.setattr(self_update, "_git", fake_git)

    resultat = self_update.appliquer_mise_a_jour()

    assert resultat["succes"] is False
    assert "réseau indisponible" in resultat["erreur"]
    assert not sentinel.exists()


def test_redemarrer_apres_delai_programme_un_timer_sans_bloquer(monkeypatch):
    appels = []

    class FauxTimer:
        def __init__(self, delay, fn):
            appels.append({"delay": delay, "fn": fn, "started": False})

        def start(self):
            appels[-1]["started"] = True

    monkeypatch.setattr(self_update.threading, "Timer", FauxTimer)

    self_update.redemarrer_apres_delai(3.0)

    assert len(appels) == 1
    assert appels[0]["delay"] == 3.0
    assert appels[0]["started"] is True
