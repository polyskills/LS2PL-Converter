# Déploiement sur serveur Linux (service, disque persistant)

Équivalent Linux de `deploy/windows/` et `deploy/macos/` (voir ces dossiers
pour les versions Windows et Mac). Cette option héberge l'application en
continu sur un serveur Linux partagé, accessible à toute l'équipe via une
URL réseau (`http://<serveur>:8501`). **Le disque est réellement
persistant** : le référentiel et l'historique de chaque client ne sont
jamais perdus au redémarrage.

Le service est géré via **systemd**, présent par défaut sur la quasi-totalité
des distributions serveur actuelles (Ubuntu, Debian, RHEL, Fedora, Rocky/Alma
Linux, etc.) : démarre au boot, redémarre seul en cas de plantage —
l'équivalent fonctionnel du service Windows géré par NSSM ou du LaunchDaemon
macOS.

## Prérequis

- Une distribution Linux basée sur systemd, avec droits `sudo`
- Python 3.10+ (`python3 --version`) — sur Debian/Ubuntu, `python3-venv` est
  aussi requis pour créer l'environnement virtuel :
  `sudo apt install python3 python3-venv python3-pip`
- Git : `sudo apt install git` (Debian/Ubuntu) ou `sudo dnf install git`
  (RHEL/Fedora)
- Accès sortant à internet le temps de l'installation (téléchargement des
  dépendances Python)

## Installation (première fois)

```bash
# 1. Cloner le dépôt à l'emplacement de votre choix
cd ~/apps  # ou tout autre dossier, ex. /opt
git clone https://github.com/polyskills/Idees.git
cd Idees
git checkout claude/lightspeed-pennylane-converter-njmeyd

# 2. Rendre les scripts exécutables (une seule fois)
chmod +x deploy/linux/*.sh

# 3. Lancer l'installation du service (nécessite sudo : création d'une
#    unité systemd système)
sudo ./deploy/linux/install-service.sh
```

Le script :
1. vérifie Python 3 et crée un environnement virtuel `.venv`
2. installe les dépendances (`requirements.txt`)
3. enregistre l'application comme service systemd (**démarrage automatique
   au boot, redémarrage automatique en cas de plantage**), exécuté sous le
   compte de l'utilisateur ayant lancé `sudo` (pas sous root, pour que les
   fichiers créés ensuite restent gérables normalement)
4. ouvre le port `8501` dans le pare-feu actif (`ufw` ou `firewalld`), s'il
   y en a un

À la fin, l'application est accessible :
- en local sur le serveur : `http://localhost:8501`
- depuis le réseau : `http://<nom-ou-IP-du-serveur>:8501`

### Personnaliser le port ou le nom du service

```bash
sudo ./deploy/linux/install-service.sh --port 8080 --service-name lspennylane-prod
```

## Service de fetch automatique des exports LightSpeed par mail (optionnel)

En complément du service applicatif, `install-email-poller-service.sh`
installe un second service systemd qui va chercher automatiquement les
exports LightSpeed reçus par mail (une boîte dédiée par client, hébergée
dans le tenant M365 **du client**), les convertit avec le même moteur que
l'import manuel, et renvoie le résultat par mail — voir `core/email_poller.py`
pour le détail du fonctionnement.

Prérequis avant installation (voir le pas-à-pas complet, création de
l'app comprise, dans
[`docs/configuration_m365_client.md`](../../docs/configuration_m365_client.md)) :
1. Une **app registration Azure AD** créée directement dans le tenant M365
   du client (single tenant, une par client), avec permission applicative
   `Mail.ReadWrite` + `Mail.Send` sur Microsoft Graph.
2. Le **consentement admin** accordé sur cette app, sur son propre tenant
   (bouton *Grant admin consent*, page API permissions de l'app).
3. Contrairement à Windows (variables d'environnement "Machine"), systemd
   n'a pas d'équivalent simple partagé entre unités : les secrets se passent
   donc en paramètres du script d'installation, qui les écrit dans l'unité
   du service (fichier ensuite lisible par root uniquement).
4. Pour chaque client concerné : tenant ID + boîte mail renseignés page
   **Réglages**, et adresse mail dédiée sur chaque point de vente page
   **Table de correspondance**.

⚠️ Les identifiants `--azure-client-id`/`--azure-client-secret` passés au
script sont **globaux au service**, donc communs à tous les clients
traités par ce serveur — cela suppose une app registration par client dont
l'ID/secret est **le même** pour tous, ce qui ne fonctionne que tant qu'**un
seul client** utilise le fetch automatique sur ce serveur. Pour plusieurs
clients simultanément, renseigner l'ID/secret **propre à chacun** dans
Réglages > Gestion Email évite complètement cette limite.

Puis, dans le même terminal, après `install-service.sh` :
```bash
sudo ./deploy/linux/install-email-poller-service.sh \
    --azure-client-id "<app id>" \
    --azure-client-secret "<secret>" \
    --alerte-interne "compta@polyskills.fr"
```

Ce service ne renvoie **jamais** de fichier au client en cas d'échec de
conversion (mapping manquant, fichier illisible...) — dans ce cas, seule
l'adresse `--alerte-interne` est notifiée, avec le détail de l'erreur, pour
correction manuelle du référentiel puis reprise via l'import manuel habituel.

### Modifier l'intervalle entre deux fetch

Contrairement à Windows (variable d'environnement "Machine"), systemd n'a
pas d'équivalent réglable en dehors de l'unité du service : la valeur (300
secondes par défaut) y est écrite en dur à l'installation. Pour la changer,
relancer l'installation avec `--poll-interval` (elle arrête et recrée le
service proprement, avec les mêmes `--azure-client-id`/`--azure-client-secret`
si vous les utilisiez) :

```bash
sudo ./deploy/linux/install-email-poller-service.sh --poll-interval 120
```

Alternative sans réinstaller : éditer directement la ligne
`Environment=LSPENNYLANE_POLL_INTERVAL_SECONDS=...` dans
`/etc/systemd/system/lightspeed-pennylane-fetchmail.service` (nom de
fichier différent si `--service-name` personnalisé à l'installation), puis
recharger et redémarrer :

```bash
sudo systemctl daemon-reload
sudo systemctl restart lightspeed-pennylane-fetchmail
```

## Mettre à jour l'application

À chaque évolution du code (nouveau commit sur la branche) :

```bash
cd ~/apps/Idees
sudo ./deploy/linux/update-service.sh
```

Ce script arrête le service, récupère la dernière version (`git pull`),
réinstalle les dépendances si besoin, puis redémarre le service. Vérifiez
ensuite que le **hash de version** affiché dans le menu latéral de
l'application correspond bien au dernier commit sur GitHub.

**Alternative sans accès terminal/admin** : page **Réglages → Informations →
Mise à jour de l'application**, un bouton fait la même chose (git pull +
dépendances si besoin) directement depuis le navigateur, puis redémarre
l'app et le service de fetch mail — pratique pour appliquer un correctif
urgent sans passer par quelqu'un ayant un accès serveur. Repose sur
`Restart=always` déjà posé par `install-service.sh` sur l'unité systemd :
l'app s'arrête simplement, systemd la relance seule.

## Désinstaller le service

```bash
cd ~/apps/Idees
sudo ./deploy/linux/uninstall-service.sh
```

Arrête et supprime le service ainsi que la règle de pare-feu. Le code, les
dépendances (`.venv`) et surtout **les données clients (`data/clients/`)
sont conservés** — seule la couche "service" est retirée.

## Administration courante

| Action | Commande |
|---|---|
| Voir le statut du service | `sudo systemctl status lightspeed-pennylane` |
| Arrêter | `sudo systemctl stop lightspeed-pennylane` |
| Démarrer | `sudo systemctl start lightspeed-pennylane` |
| Redémarrer | `sudo systemctl restart lightspeed-pennylane` |
| Voir les logs (fichiers) | `Idees/logs/service.out.log` et `service.err.log` |
| Voir les logs (journal systemd) | `sudo journalctl -u lightspeed-pennylane -f` |
| Modifier la config du service (avancé) | `sudo systemctl edit --full lightspeed-pennylane` puis `sudo systemctl daemon-reload` |

## Sauvegarde des données

Les données comptables des clients vivent dans `Idees/data/clients/`
(référentiels + historique des conversions, fichiers source et générés).
**Ce dossier n'est pas versionné dans git** (données sensibles) — mettez en
place une sauvegarde régulière de ce dossier (copie planifiée via `cron`,
outil de sauvegarde habituel du serveur, etc.), il n'existe nulle part
ailleurs.

## Sécuriser l'accès

⚠️ Tel quel, l'application n'a **aucune authentification** : quiconque
accède à l'URL du serveur voit tous les clients. Pour un accès réseau
partagé, envisager au minimum l'un de :
- restreindre l'accès réseau au port `8501` (pare-feu / VLAN / VPN
  interne uniquement, pas d'exposition directe sur internet)
- mettre un reverse proxy (nginx, Caddy) devant l'application avec
  authentification (Basic Auth, SSO d'entreprise...) et HTTPS
- demander une évolution de l'application pour une authentification
  applicative native (comptes utilisateurs)

## Dépannage

**Le service ne démarre pas** : consulter `Idees/logs/service.err.log` et
`sudo journalctl -u lightspeed-pennylane -n 50 --no-pager`. Cause fréquente :
port déjà utilisé par une autre application (relancer l'installation avec
`--port` sur un autre port), ou dépendance manquante (relancer
`sudo ./deploy/linux/update-service.sh`).

**Page inaccessible depuis un autre poste** : vérifier le pare-feu
(`sudo ufw status` ou `sudo firewall-cmd --list-ports`) — l'installation
l'a normalement déjà configuré si actif, sinon ouvrir le port manuellement.
Vérifier aussi qu'aucun pare-feu réseau (routeur, VLAN, groupe de sécurité
cloud) ne bloque le port en amont.

**python3 introuvable** : installer Python via le gestionnaire de paquets de
la distribution (`sudo apt install python3 python3-venv` sur Debian/Ubuntu,
`sudo dnf install python3` sur RHEL/Fedora).

**`sudo` obligatoire** : la création d'une unité systemd système
(`/etc/systemd/system/`) nécessite les droits administrateur — c'est
l'équivalent du "PowerShell en tant qu'administrateur" requis côté Windows.

**Pas de systemd (autre init)** : ces scripts ciblent spécifiquement
systemd. Sur une distribution utilisant une autre init (ex. OpenRC, sysvinit
sur certains systèmes embarqués/minimalistes), il faudra adapter
manuellement le lancement en service — la commande à exécuter reste
`.venv/bin/python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true`.
