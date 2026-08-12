#!/usr/bin/env bash
#
# Installe le service de fetch automatique des exports LightSpeed reçus par
# mail (email_poller.py), équivalent macOS de
# deploy/windows/install-email-poller-service.ps1 — même dépôt, même .venv.
#
# A exécuter avec sudo, depuis la RACINE du dépôt cloné, APRES
# install-service.sh (réutilise le même environnement virtuel).
#
# Contrairement à Windows (variables d'environnement "Machine"), macOS n'a
# pas d'équivalent simple pour un LaunchDaemon : les secrets sont donc passés
# en paramètres du script, qui les écrit dans le plist du service (fichier
# lisible par root uniquement, cf. chmod 600 plus bas).
#
# Le tenant M365 et la boîte mail à interroger se configurent, eux, par
# client dans l'application (page Clients) — pas via ce script.
#
# Exemple :
#   sudo ./deploy/macos/install-email-poller-service.sh \
#       --azure-client-id "<app id>" \
#       --azure-client-secret "<secret>" \
#       --alerte-interne "compta@polyskills.fr"
#
set -euo pipefail

SERVICE_NAME="lightspeed-pennylane-fetchmail"
AZURE_CLIENT_ID=""
AZURE_CLIENT_SECRET=""
ALERTE_INTERNE=""
POLL_INTERVAL="300"

while [ $# -gt 0 ]; do
    case "$1" in
        --service-name) SERVICE_NAME="$2"; shift 2 ;;
        --azure-client-id) AZURE_CLIENT_ID="$2"; shift 2 ;;
        --azure-client-secret) AZURE_CLIENT_SECRET="$2"; shift 2 ;;
        --alerte-interne) ALERTE_INTERNE="$2"; shift 2 ;;
        --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo (nécessaire pour installer un LaunchDaemon)." >&2
    exit 1
fi
if [ -z "$AZURE_CLIENT_ID" ] || [ -z "$AZURE_CLIENT_SECRET" ]; then
    echo "Paramètres requis manquants : --azure-client-id et --azure-client-secret." >&2
    exit 1
fi

REAL_USER="${SUDO_USER:-$(id -un)}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ ! -f "$REPO_ROOT/email_poller.py" ]; then
    echo "email_poller.py introuvable dans '$REPO_ROOT'. Lancez ce script depuis la RACINE du dépôt cloné." >&2
    exit 1
fi

VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "$VENV_PYTHON introuvable — lancez d'abord install-service.sh (crée l'environnement virtuel partagé)." >&2
    exit 1
fi
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet

LABEL="com.polyskills.$SERVICE_NAME"
PLIST_PATH="/Library/LaunchDaemons/$LABEL.plist"
LOGS_DIR="$REPO_ROOT/logs"
mkdir -p "$LOGS_DIR"
chown "$REAL_USER" "$LOGS_DIR"

if launchctl print "system/$LABEL" >/dev/null 2>&1; then
    echo "Le service '$LABEL' existe déjà : arrêt avant réinstallation..."
    launchctl bootout "system/$LABEL" 2>/dev/null || true
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>UserName</key>
    <string>$REAL_USER</string>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>email_poller.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LSPENNYLANE_AZURE_CLIENT_ID</key>
        <string>$AZURE_CLIENT_ID</string>
        <key>LSPENNYLANE_AZURE_CLIENT_SECRET</key>
        <string>$AZURE_CLIENT_SECRET</string>
        <key>LSPENNYLANE_ALERTE_INTERNE</key>
        <string>$ALERTE_INTERNE</string>
        <key>LSPENNYLANE_POLL_INTERVAL_SECONDS</key>
        <string>$POLL_INTERVAL</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOGS_DIR/email-poller.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/email-poller.err.log</string>
</dict>
</plist>
PLIST

chown root:wheel "$PLIST_PATH"
chmod 600 "$PLIST_PATH"  # contient le secret Azure AD : lecture réservée à root

launchctl bootstrap system "$PLIST_PATH"
launchctl enable "system/$LABEL"
launchctl kickstart -k "system/$LABEL"

sleep 2
echo
echo "=== Installation terminée ==="
launchctl print "system/$LABEL" 2>/dev/null | grep -E "state|pid" || true
echo "Logs : $LOGS_DIR/email-poller.*.log"
