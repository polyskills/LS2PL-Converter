#!/usr/bin/env bash
#
# Installe le service de fetch automatique des exports LightSpeed reçus par
# mail (email_poller.py), équivalent Linux de
# deploy/windows/install-email-poller-service.ps1 /
# deploy/macos/install-email-poller-service.sh — même dépôt, même .venv.
#
# A exécuter avec sudo, depuis la RACINE du dépôt cloné, APRES
# install-service.sh (réutilise le même environnement virtuel).
#
# --azure-client-id/--azure-client-secret sont optionnels : ils ne servent
# que de repli GLOBAL pour un client sans identifiants Azure propres
# renseignés dans LS2PL (page Réglages > Gestion Email, recommandé — un jeu
# d'identifiants par client, cf. docs/configuration_m365_client.md). Si tous
# les clients ont leurs propres identifiants, ces deux options peuvent être
# omises. Contrairement à Windows (variables d'environnement "Machine"),
# systemd n'a pas d'équivalent simple partagé entre unités : ce repli est
# donc passé en paramètre du script, qui l'écrit dans l'unité du service
# (fichier ensuite lisible par root uniquement, cf. chmod 600 plus bas).
#
# Le tenant M365 et la boîte mail à interroger se configurent, eux, par
# client dans l'application (page Réglages) — pas via ce script.
#
# Exemple :
#   sudo ./deploy/linux/install-email-poller-service.sh \
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
    echo "Ce script doit être exécuté avec sudo (nécessaire pour installer une unité systemd)." >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd (systemctl) introuvable. Ce script cible les distributions Linux basées sur systemd." >&2
    exit 1
fi
if [ -z "$AZURE_CLIENT_ID" ] || [ -z "$AZURE_CLIENT_SECRET" ]; then
    echo "⚠️  --azure-client-id/--azure-client-secret non fournis : aucun repli global." >&2
    echo "    Seuls les clients avec leurs propres identifiants Azure (LS2PL > Réglages" >&2
    echo "    > Gestion Email) seront traités par le fetch automatique." >&2
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
Description=LightSpeed - Fetch mail automatique
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$REPO_ROOT
Environment=LSPENNYLANE_AZURE_CLIENT_ID=$AZURE_CLIENT_ID
Environment=LSPENNYLANE_AZURE_CLIENT_SECRET=$AZURE_CLIENT_SECRET
Environment=LSPENNYLANE_ALERTE_INTERNE=$ALERTE_INTERNE
Environment=LSPENNYLANE_POLL_INTERVAL_SECONDS=$POLL_INTERVAL
ExecStart=$VENV_PYTHON email_poller.py
Restart=always
RestartSec=3
StandardOutput=append:$LOGS_DIR/email-poller.out.log
StandardError=append:$LOGS_DIR/email-poller.err.log

[Install]
WantedBy=multi-user.target
UNIT

chmod 600 "$UNIT_PATH"  # contient le secret Azure AD : lecture réservée à root

# Sentinelle de redémarrage (core.self_update.appliquer_mise_a_jour) : posée par
# l'app à chaque mise à jour applicative pour faire redémarrer un service de fetch
# mail déjà EN COURS D'EXÉCUTION. Une mise à jour appliquée avant l'installation de
# CE service laisse ce fichier trainer sans qu'il ait jamais été lu - au tout
# premier démarrage ci-dessous, email_poller.py la trouve, l'interprète comme "un
# redémarrage vient d'être demandé" et s'arrête après quelques secondes (log
# "Redémarrage demandé depuis l'application"). Avec Restart=always, systemd le
# relance aussitôt sans dommage (pas de protection anti-boucle façon NSSM ici),
# mais elle est de toute façon sans objet pour un service qui vient d'être
# (ré)installé avec du code déjà à jour : purgée avant le premier démarrage.
rm -f "$REPO_ROOT/data/.fetch_mail_restart_requested"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

sleep 2
echo
echo "=== Installation terminée ==="
systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null | head -5 || true
echo "Logs : $LOGS_DIR/email-poller.*.log"
