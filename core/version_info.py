"""
Identifie précisément la version du code réellement en cours d'exécution
(commit Git), pour pouvoir vérifier, après un déploiement, que l'app tourne
bien sur la dernière version poussée — plutôt que de le supposer.
"""
from __future__ import annotations

import os
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_version_info() -> dict:
    """Interroge git directement (pas de fichier généré à la build) : la valeur
    retournée reflète toujours exactement le commit sur lequel le processus
    Streamlit en cours a été démarré."""
    info = {"hash": None, "date": None, "message": None, "branch": None, "dirty": False}

    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return out.stdout.strip()
        except Exception:
            return None

    log = _git("log", "-1", "--format=%h|%cI|%s")
    if log and "|" in log:
        h, date, msg = log.split("|", 2)
        info["hash"] = h
        info["date"] = date
        info["message"] = msg

    info["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")

    status = _git("status", "--porcelain")
    info["dirty"] = bool(status)

    return info
