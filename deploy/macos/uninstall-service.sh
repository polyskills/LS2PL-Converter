#!/usr/bin/env bash
#
# Désinstalle un service macOS du convertisseur LightSpeed -> Pennylane
# (arrête et supprime le LaunchDaemon), équivalent de
# deploy/windows/uninstall-service.ps1.
#
# N'efface PAS les données (data/clients/), le code, ni l'environnement
# virtuel (.venv) : seule la couche "service" est retirée.
#
# Exemples :
#   sudo ./deploy/macos/uninstall-service.sh
#   sudo ./deploy/macos/uninstall-service.sh --service-name lightspeed-pennylane-fetchmail
#
set -euo pipefail

SERVICE_NAME="lightspeed-pennylane"

while [ $# -gt 0 ]; do
    case "$1" in
        --service-name) SERVICE_NAME="$2"; shift 2 ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo." >&2
    exit 1
fi

LABEL="com.polyskills.$SERVICE_NAME"
PLIST_PATH="/Library/LaunchDaemons/$LABEL.plist"

echo "Arrêt et suppression du service '$LABEL'..."
launchctl bootout "system/$LABEL" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Service désinstallé. Le code, .venv et data/clients/ sont conservés."
