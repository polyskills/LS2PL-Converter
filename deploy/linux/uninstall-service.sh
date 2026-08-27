#!/usr/bin/env bash
#
# Désinstalle un service Linux du convertisseur LightSpeed -> Pennylane
# (arrête et supprime l'unité systemd + la règle de pare-feu associée),
# équivalent de deploy/windows/uninstall-service.ps1.
#
# N'efface PAS les données (data/clients/), le code, ni l'environnement
# virtuel (.venv) : seule la couche "service" est retirée.
#
# Exemples :
#   sudo ./deploy/linux/uninstall-service.sh
#   sudo ./deploy/linux/uninstall-service.sh --service-name lightspeed-pennylane-fetchmail
#   sudo ./deploy/linux/uninstall-service.sh --port 8080
#
set -euo pipefail

SERVICE_NAME="lightspeed-pennylane"
PORT=8501

while [ $# -gt 0 ]; do
    case "$1" in
        --service-name) SERVICE_NAME="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo." >&2
    exit 1
fi

UNIT_PATH="/etc/systemd/system/$SERVICE_NAME.service"

echo "Arrêt et suppression du service '$SERVICE_NAME'..."
systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
rm -f "$UNIT_PATH"
systemctl daemon-reload

# Retire la règle de pare-feu ouverte par install-service.sh, si présente.
# Sans objet pour le service de fetch mail (--port n'a alors pas de sens :
# ce service n'ouvre aucun port entrant) — ne fait rien si le port n'y est
# pour rien dans l'accès de l'utilisateur.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi "active"; then
    ufw delete allow "$PORT/tcp" >/dev/null 2>&1 || true
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --permanent --remove-port="$PORT/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
fi

echo "Service désinstallé. Le code, .venv et data/clients/ sont conservés."
