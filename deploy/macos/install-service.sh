#!/usr/bin/env bash
#
# Installe le convertisseur LightSpeed -> Pennylane comme service macOS
# (LaunchDaemon : démarre au boot, redémarre seul en cas de plantage),
# équivalent macOS de deploy/windows/install-service.ps1 (NSSM).
#
# A exécuter avec sudo, depuis la RACINE du dépôt cloné (le dossier qui
# contient app.py).
#
# Le script :
#   1. Vérifie Python 3 et crée un environnement virtuel .venv
#   2. Installe les dépendances (requirements.txt)
#   3. Enregistre le service macOS (LaunchDaemon) et le démarre
#   4. Autorise Python dans le pare-feu applicatif macOS si celui-ci est actif
#
# Exemples :
#   sudo ./deploy/macos/install-service.sh
#   sudo ./deploy/macos/install-service.sh --port 8080 --service-name lspennylane-prod
#
set -euo pipefail

PORT=8501
SERVICE_NAME="lightspeed-pennylane"

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --service-name) SERVICE_NAME="$2"; shift 2 ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo (nécessaire pour installer un LaunchDaemon)." >&2
    exit 1
fi

# Utilisateur réel (celui qui a lancé sudo) : le service tourne sous ce
# compte plutôt que sous root, pour que les fichiers créés ensuite
# (data/clients, logs) restent gérables normalement au quotidien.
REAL_USER="${SUDO_USER:-$(id -un)}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ ! -f "$REPO_ROOT/app.py" ]; then
    echo "app.py introuvable dans '$REPO_ROOT'. Lancez ce script depuis la RACINE du dépôt cloné (ex: cd ~/Apps/Idees)." >&2
    exit 1
fi

echo "=== Convertisseur LightSpeed -> Pennylane : installation en service macOS ==="
echo "Dossier de l'application : $REPO_ROOT"
echo "Compte d'exécution du service : $REAL_USER"

# --- 1. Python ---------------------------------------------------------------
echo
echo "[1/4] Vérification de Python..."
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "python3 introuvable dans le PATH. Installez-le d'abord, par exemple : brew install python@3.12" >&2
    exit 1
fi
echo "Python détecté : $("$PYTHON_BIN" --version)"

VENV_DIR="$REPO_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Création de l'environnement virtuel (.venv)..."
    sudo -u "$REAL_USER" "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "Environnement virtuel déjà présent (.venv)."
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Échec de création de l'environnement virtuel : $VENV_PYTHON introuvable." >&2
    exit 1
fi

# --- 2. Dépendances -----------------------------------------------------------
echo
echo "[2/4] Installation des dépendances (requirements.txt)..."
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install --upgrade pip --quiet
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet
echo "Dépendances installées."

# --- 3. LaunchDaemon -----------------------------------------------------------
echo
echo "[3/4] Enregistrement du service '$SERVICE_NAME'..."

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
        <string>-m</string>
        <string>streamlit</string>
        <string>run</string>
        <string>app.py</string>
        <string>--server.port</string>
        <string>$PORT</string>
        <string>--server.address</string>
        <string>0.0.0.0</string>
        <string>--server.headless</string>
        <string>true</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOGS_DIR/service.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/service.err.log</string>
</dict>
</plist>
PLIST

chown root:wheel "$PLIST_PATH"
chmod 644 "$PLIST_PATH"

launchctl bootstrap system "$PLIST_PATH"
launchctl enable "system/$LABEL"
launchctl kickstart -k "system/$LABEL"

echo "Service '$LABEL' démarré."

# --- 4. Pare-feu applicatif macOS ----------------------------------------------
echo
echo "[4/4] Vérification du pare-feu applicatif macOS..."
FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [ -x "$FW" ] && "$FW" --getglobalstate 2>/dev/null | grep -qi "enabled"; then
    echo "Pare-feu applicatif actif : autorisation des connexions entrantes pour Python..."
    "$FW" --add "$VENV_PYTHON" >/dev/null 2>&1 || true
    "$FW" --unblockapp "$VENV_PYTHON" >/dev/null 2>&1 || true
else
    echo "Pare-feu applicatif désactivé ou absent : rien à faire."
fi

sleep 2
echo
echo "=== Installation terminée ==="
launchctl print "system/$LABEL" 2>/dev/null | grep -E "state|pid" || true
echo "Accès local  : http://localhost:$PORT"
echo "Accès réseau : http://$(scutil --get LocalHostName 2>/dev/null || hostname).local:$PORT (ou http://<IP du Mac>:$PORT)"
echo "Logs         : $LOGS_DIR"
