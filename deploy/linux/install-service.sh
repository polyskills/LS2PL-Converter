#!/usr/bin/env bash
#
# Installe le convertisseur LightSpeed -> Pennylane comme service Linux
# (unité systemd : démarre au boot, redémarre seul en cas de plantage),
# équivalent Linux de deploy/windows/install-service.ps1 (NSSM) et
# deploy/macos/install-service.sh (launchd).
#
# A exécuter avec sudo, depuis la RACINE du dépôt cloné (le dossier qui
# contient app.py). Nécessite systemd (Ubuntu, Debian, RHEL/Fedora, etc.).
#
# Le script :
#   1. Vérifie Python 3 et crée un environnement virtuel .venv
#   2. Installe les dépendances (requirements.txt)
#   3. Enregistre le service systemd et le démarre
#   4. Ouvre le port dans le pare-feu actif (ufw ou firewalld), si présent
#
# Exemples :
#   sudo ./deploy/linux/install-service.sh
#   sudo ./deploy/linux/install-service.sh --port 8080 --service-name lspennylane-prod
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
    echo "Ce script doit être exécuté avec sudo (nécessaire pour installer une unité systemd)." >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd (systemctl) introuvable. Ce script cible les distributions Linux basées sur systemd" >&2
    echo "(Ubuntu, Debian, RHEL/Fedora, etc.) — sur une autre init, adapter manuellement l'unité." >&2
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

echo "=== Convertisseur LightSpeed -> Pennylane : installation en service Linux ==="
echo "Dossier de l'application : $REPO_ROOT"
echo "Compte d'exécution du service : $REAL_USER"

# --- 1. Python ---------------------------------------------------------------
echo
echo "[1/4] Vérification de Python..."
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "python3 introuvable dans le PATH. Installez-le d'abord, par exemple :" >&2
    echo "  Debian/Ubuntu : sudo apt install python3 python3-venv" >&2
    echo "  RHEL/Fedora   : sudo dnf install python3" >&2
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
    echo "Sur Debian/Ubuntu, il manque probablement le paquet python3-venv (sudo apt install python3-venv)." >&2
    exit 1
fi

# --- 2. Dépendances -----------------------------------------------------------
echo
echo "[2/4] Installation des dépendances (requirements.txt)..."
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install --upgrade pip --quiet
sudo -u "$REAL_USER" "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt" --quiet
echo "Dépendances installées."

# --- 3. Unité systemd -----------------------------------------------------------
echo
echo "[3/4] Enregistrement du service '$SERVICE_NAME'..."

UNIT_PATH="/etc/systemd/system/$SERVICE_NAME.service"
LOGS_DIR="$REPO_ROOT/logs"
mkdir -p "$LOGS_DIR"
chown "$REAL_USER" "$LOGS_DIR"

if [ -f "$UNIT_PATH" ]; then
    echo "Le service '$SERVICE_NAME' existe déjà : arrêt avant réinstallation..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi

cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=LightSpeed -> Pennylane (convertisseur comptable, port $PORT)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$REPO_ROOT
ExecStart=$VENV_PYTHON -m streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=3
StandardOutput=append:$LOGS_DIR/service.out.log
StandardError=append:$LOGS_DIR/service.err.log

[Install]
WantedBy=multi-user.target
UNIT

chmod 644 "$UNIT_PATH"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo "Service '$SERVICE_NAME' démarré."

# --- 4. Pare-feu ----------------------------------------------------------------
echo
echo "[4/4] Vérification du pare-feu..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi "active"; then
    echo "ufw actif : ouverture du port $PORT/tcp..."
    ufw allow "$PORT/tcp" >/dev/null
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    echo "firewalld actif : ouverture du port $PORT/tcp..."
    firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null
    firewall-cmd --reload >/dev/null
else
    echo "Aucun pare-feu actif détecté (ufw/firewalld) : rien à faire. Vérifiez un éventuel pare-feu"
    echo "réseau en amont (routeur, groupe de sécurité cloud...) si l'accès distant échoue."
fi

sleep 2
echo
echo "=== Installation terminée ==="
systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null | head -5 || true
echo "Accès local  : http://localhost:$PORT"
echo "Accès réseau : http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT (ou http://$(hostname):$PORT selon la résolution DNS locale)"
echo "Logs         : $LOGS_DIR"
