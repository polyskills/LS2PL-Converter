"""
Mise à jour de l'application depuis l'interface web : va chercher le
dernier commit de la branche suivie, l'applique, réinstalle les
dépendances si besoin, puis redémarre l'app elle-même ET le service de
fetch mail (`email_poller.py`), sans passer par un accès terminal/admin.

Ne fonctionne QUE sur un déploiement serveur (Windows/macOS, cf. deploy/) :
- suppose un dépôt git réel sur disque, avec un accès réseau au remote ;
- suppose que le process est supervisé par un gestionnaire de service
  configuré pour le redémarrer automatiquement à sa sortie (NSSM avec
  "AppExit Default Restart" côté Windows, LaunchDaemon avec KeepAlive côté
  macOS - déjà le cas par défaut avec deploy/windows/install-service.ps1 et
  deploy/macos/install-service.sh).

Redémarrage du service de fetch mail : contrairement à l'app elle-même
(qui peut simplement s'arrêter et laisser son propre superviseur la
relancer), ce process tourne dans un SERVICE SÉPARÉ. Plutôt que de lui
donner l'ordre de redémarrer via des commandes systèmes privilégiées
(nssm/launchctl - sur macOS le service applicatif tourne délibérément sous
un compte non-root, cf. deploy/macos/install-service.sh, et n'a donc pas
les droits pour piloter un LaunchDaemon system), on dépose un simple
fichier sentinelle que email_poller.py surveille entre deux cycles et
efface en sortant : symétrique du mécanisme utilisé pour l'app elle-même
(sortie du process, redémarrage par le superviseur), sans élévation de
privilèges ni commande système spécifique à l'OS.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS_PATH = os.path.join(BASE_DIR, "requirements.txt")

# Sentinelle lue par email_poller.py (racine) entre deux cycles : sa seule
# présence vaut demande de redémarrage, le contenu n'est pas interprété.
# Dans data/ (non versionné, disque local du serveur) comme le reste de
# l'état runtime de l'app.
RESTART_SENTINEL_EMAIL_POLLER = os.path.join(BASE_DIR, "data", ".fetch_mail_restart_requested")


def _git(*args: str, timeout: int = 15) -> tuple[bool, str]:
    """Exécute une commande git dans le dépôt de l'app. Retourne (succès,
    sortie standard ou message d'erreur) plutôt que de lever une exception :
    chaque étape de la mise à jour doit pouvoir échouer proprement sans
    laisser le process dans un état intermédiaire silencieux."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",  # sans ça, Windows décode avec la page de code par défaut (souvent
            # CP1252, pas UTF-8) : messages de commit accentués affichés en mojibake.
            timeout=timeout,
        )
        if out.returncode != 0:
            return False, (out.stderr or out.stdout or f"git {' '.join(args)} a échoué").strip()
        return True, out.stdout.strip()
    except FileNotFoundError:
        return False, "git introuvable sur ce serveur."
    except subprocess.TimeoutExpired:
        return False, f"git {' '.join(args)} n'a pas répondu (délai dépassé)."
    except Exception as exc:  # pragma: no cover - filet de sécurité générique
        return False, str(exc)


def _hash_fichier(chemin: str) -> str | None:
    if not os.path.exists(chemin):
        return None
    with open(chemin, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def verifier_mise_a_jour() -> dict:
    """Compare le commit local à la dernière version de la branche suivie
    sur le remote. Ne modifie rien sur le disque (git fetch seul)."""
    resultat = {
        "disponible": None,  # None = impossible de vérifier (pas un dépôt git, pas de réseau...)
        "a_jour": None,
        "branche": None,
        "commit_local": None,
        "commit_distant": None,
        "message_distant": None,
        "erreur": None,
    }

    ok, branche = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not ok or branche == "HEAD":  # "HEAD" = dépôt en detached HEAD, cas non géré ici
        resultat["erreur"] = branche if not ok else "Le dépôt n'est pas sur une branche suivie (HEAD détaché)."
        return resultat
    resultat["branche"] = branche

    ok, sortie = _git("fetch", "origin", branche, timeout=30)
    if not ok:
        resultat["erreur"] = f"Échec de la récupération des dernières infos ({sortie})."
        return resultat

    ok, local = _git("rev-parse", "HEAD")
    if not ok:
        resultat["erreur"] = local
        return resultat
    ok, distant = _git("rev-parse", f"origin/{branche}")
    if not ok:
        resultat["erreur"] = distant
        return resultat

    resultat["commit_local"] = local[:8]
    resultat["commit_distant"] = distant[:8]
    resultat["a_jour"] = local == distant
    resultat["disponible"] = True

    if not resultat["a_jour"]:
        _, message = _git("log", "-1", "--format=%s", f"origin/{branche}")
        resultat["message_distant"] = message

    return resultat


def appliquer_mise_a_jour() -> dict:
    """Applique la dernière version de la branche suivie (écrase tout
    changement local non commité sur un fichier suivi par git - jamais
    data/, non versionné), réinstalle les dépendances si requirements.txt a
    changé, et dépose la sentinelle de redémarrage du service de fetch mail.
    Ne redémarre PAS l'app elle-même : à la charge de l'appelant (page
    Réglages), pour pouvoir d'abord afficher un message de confirmation."""
    resultat = {"succes": False, "nouveau_commit": None, "erreur": None, "dependances_reinstallees": False}

    ok, branche = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not ok:
        resultat["erreur"] = branche
        return resultat

    ok, _ = _git("fetch", "origin", branche, timeout=30)
    if not ok:
        resultat["erreur"] = f"Échec de la récupération de la dernière version : {_}"
        return resultat

    hash_avant = _hash_fichier(REQUIREMENTS_PATH)

    ok, sortie = _git("reset", "--hard", f"origin/{branche}", timeout=30)
    if not ok:
        resultat["erreur"] = f"Échec de l'application de la mise à jour : {sortie}"
        return resultat

    hash_apres = _hash_fichier(REQUIREMENTS_PATH)
    if hash_avant != hash_apres:
        try:
            import sys
            pip = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_PATH, "--quiet"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
            )
            if pip.returncode != 0:
                resultat["erreur"] = f"Code mis à jour mais échec de l'installation des dépendances : {pip.stderr.strip()}"
                return resultat
            resultat["dependances_reinstallees"] = True
        except Exception as exc:
            resultat["erreur"] = f"Code mis à jour mais échec de l'installation des dépendances : {exc}"
            return resultat

    os.makedirs(os.path.dirname(RESTART_SENTINEL_EMAIL_POLLER), exist_ok=True)
    with open(RESTART_SENTINEL_EMAIL_POLLER, "w", encoding="utf-8") as f:
        f.write("redémarrage demandé par la mise à jour applicative\n")

    _, nouveau_commit = _git("rev-parse", "--short", "HEAD")
    resultat["succes"] = True
    resultat["nouveau_commit"] = nouveau_commit
    return resultat


def redemarrer_apres_delai(secondes: float = 5.0) -> None:
    """Programme l'arrêt du process courant après un court délai, pour
    laisser le temps au message de confirmation (ET au script de
    redirection automatique, cf. pages/reglages.py) de bien être livrés au
    navigateur avant la coupure — sur un réseau réel (pas juste localhost),
    la marge de 2s initialement retenue s'est révélée trop courte : le
    process pouvait sortir avant que le rerun Streamlit n'ait fini d'être
    transmis par le WebSocket, laissant le script de redirection jamais
    injecté dans la page. Le redémarrage effectif est délégué au
    superviseur du service (NSSM/LaunchDaemon), pas géré ici : ce process
    se contente de sortir."""
    threading.Timer(secondes, lambda: os._exit(0)).start()
