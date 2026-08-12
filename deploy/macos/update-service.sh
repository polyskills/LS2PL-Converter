#!/usr/bin/env bash
#
# Met à jour l'application (git pull + dépendances) puis redémarre le
# service macOS, équivalent de deploy/windows/update-service.ps1.
#
# A exécuter avec sudo, depuis la racine du dépôt cloné :
#   sudo ./deploy/macos/update-service.sh
#
set -euo pipefail

SERVICE_NAME="lightspeed-pennylane"
BRANCH="claude/lightspeed-pennylane-converter-njmeyd"

while [ $# -gt 0 ]; do
    case "$1" in
        --service-name) SERVICE_NAME="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ ! -f "$REPO_ROOT/app.py" ]; then
    echo "app.py introuvable dans '$REPO_ROOT'. Lancez ce script depuis la racine du dépôt." >&2
    exit 1
fi

REAL_USER="${SUDO_USER:-$(id -un)}"
LABEL="com.polyskills.$SERVICE_NAME"
PLIST_PATH="/Library/LaunchDaemons/$LABEL.plist"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

echo "Arrêt du service '$LABEL'..."
launchctl bootout "system/$LABEL" 2>/dev/null || true

echo "Récupération de la dernière version (branche $BRANCH)..."
cd "$REPO_ROOT"
sudo -u "$REAL_USER" git fetch origin "$BRANCH"
sudo -u "$REAL_USER" git checkout "$BRANCH"
sudo -u "$REAL_USER" git pull origin "$BRANCH"

echo "Mise à jour des dépendances..."
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet

echo "Redémarrage du service..."
launchctl bootstrap system "$PLIST_PATH"
launchctl kickstart -k "system/$LABEL"

echo "Terminé. Vérifiez le hash de version affiché dans le menu latéral de l'application."
