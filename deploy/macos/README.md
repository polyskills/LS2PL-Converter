# Déploiement sur Mac (service, disque persistant)

Équivalent macOS de `deploy/windows/` (voir ce dossier pour la version
Windows). Cette option héberge l'application en continu sur un Mac
partagé, accessible à toute l'équipe via une URL réseau
(`http://<nom-du-mac>.local:8501`). Contrairement à Streamlit Community
Cloud, **le disque est réellement persistant** : le référentiel et
l'historique de chaque client ne sont plus perdus à chaque redémarrage.

Le service est géré via **launchd** (le gestionnaire de services natif
macOS), sous la forme d'un LaunchDaemon : démarre au boot (sans avoir besoin
d'ouvrir de session), redémarre seul en cas de plantage — l'équivalent
fonctionnel du service Windows géré par NSSM.

## Prérequis

- macOS (Intel ou Apple Silicon), avec droits administrateur (`sudo`)
- [Python 3.10+](https://www.python.org/downloads/macos/), par exemple via
  Homebrew : `brew install python@3.12`
- Git : déjà présent si les outils en ligne de commande Xcode sont
  installés (`xcode-select --install`), sinon `brew install git`
- Accès sortant à internet le temps de l'installation (téléchargement des
  dépendances Python)

## Installation (première fois)

Ouvrir **Terminal**, puis :

```bash
# 1. Cloner le dépôt à l'emplacement de votre choix
cd ~/Applications  # ou tout autre dossier
git clone https://github.com/polyskills/Idees.git
cd Idees
git checkout claude/lightspeed-pennylane-converter-njmeyd

# 2. Rendre les scripts exécutables (une seule fois)
chmod +x deploy/macos/*.sh

# 3. Lancer l'installation du service (nécessite sudo : création d'un
#    LaunchDaemon système)
sudo ./deploy/macos/install-service.sh
```

Le script :
1. vérifie Python 3 et crée un environnement virtuel `.venv`
2. installe les dépendances (`requirements.txt`)
3. enregistre l'application comme LaunchDaemon (**démarrage automatique au
   boot, redémarrage automatique en cas de plantage**), exécuté sous le
   compte de l'utilisateur ayant lancé `sudo` (pas sous root, pour que les
   fichiers créés ensuite restent gérables normalement)
4. autorise Python dans le pare-feu applicatif macOS, s'il est activé

À la fin, l'application est accessible :
- en local sur le Mac : `http://localhost:8501`
- depuis le réseau : `http://<nom-du-mac>.local:8501` (ou son IP)

### Personnaliser le port ou le nom du service

```bash
sudo ./deploy/macos/install-service.sh --port 8080 --service-name lspennylane-prod
```

## Service de fetch automatique des exports LightSpeed par mail (optionnel)

En complément du service applicatif, `install-email-poller-service.sh`
installe un second LaunchDaemon qui va chercher automatiquement les exports
LightSpeed reçus par mail (une boîte dédiée par client, hébergée dans le
tenant M365 **du client**), les convertit avec le même moteur que l'import
manuel, et renvoie le résultat par mail — voir `core/email_poller.py` pour
le détail du fonctionnement.

Prérequis avant installation (voir le pas-à-pas complet, création de
l'app comprise, dans
[`docs/configuration_m365_client.md`](../../docs/configuration_m365_client.md)) :
1. Une **app registration Azure AD** créée directement dans le tenant M365
   du client (single tenant, une par client), avec permission applicative
   `Mail.ReadWrite` + `Mail.Send` sur Microsoft Graph.
2. Le **consentement admin** accordé sur cette app, sur son propre tenant
   (bouton *Grant admin consent*, page API permissions de l'app).
3. Contrairement à Windows (variables d'environnement "Machine"), macOS n'a
   pas d'équivalent simple pour un LaunchDaemon : les secrets se passent
   donc en paramètres du script d'installation, qui les écrit dans le plist
   du service (fichier ensuite lisible par root uniquement).
4. Pour chaque client concerné : tenant ID + boîte mail renseignés page
   **Clients**, et adresse mail dédiée sur chaque point de vente page
   **Table de correspondance**.

⚠️ Les identifiants `--azure-client-id`/`--azure-client-secret` passés au
script sont **globaux au service**, donc communs à tous les clients
traités par ce serveur — cela suppose une app registration par client dont
l'ID/secret est **le même** pour tous, ce qui ne fonctionne que tant qu'**un
seul client** utilise le fetch automatique sur ce serveur. Pour plusieurs
clients simultanément, il faudra soit une app par client avec des
identifiants distincts (nécessite d'adapter `core/email_poller.py` pour
lire des credentials par client), soit revenir à une app unique enregistrée
en multi-tenant.

Puis, dans le même Terminal, après `install-service.sh` :
```bash
sudo ./deploy/macos/install-email-poller-service.sh \
    --azure-client-id "<app id>" \
    --azure-client-secret "<secret>" \
    --alerte-interne "compta@polyskills.fr"
```

Ce service ne renvoie **jamais** de fichier au client en cas d'échec de
conversion (mapping manquant, fichier illisible...) — dans ce cas, seule
l'adresse `--alerte-interne` est notifiée, avec le détail de l'erreur, pour
correction manuelle du référentiel puis reprise via l'import manuel habituel.

## Mettre à jour l'application

À chaque évolution du code (nouveau commit sur la branche) :

```bash
cd ~/Applications/Idees
sudo ./deploy/macos/update-service.sh
```

Ce script arrête le service, récupère la dernière version (`git pull`),
réinstalle les dépendances si besoin, puis redémarre le service. Vérifiez
ensuite que le **hash de version** affiché dans le menu latéral de
l'application correspond bien au dernier commit sur GitHub.

## Désinstaller le service

```bash
cd ~/Applications/Idees
sudo ./deploy/macos/uninstall-service.sh
```

Arrête et supprime le LaunchDaemon. Le code, les dépendances (`.venv`) et
surtout **les données clients (`data/clients/`) sont conservés** — seule la
couche "service" est retirée.

## Administration courante

| Action | Commande |
|---|---|
| Voir le statut du service | `sudo launchctl print system/com.polyskills.lightspeed-pennylane` |
| Arrêter | `sudo launchctl bootout system/com.polyskills.lightspeed-pennylane` |
| Démarrer | `sudo launchctl bootstrap system /Library/LaunchDaemons/com.polyskills.lightspeed-pennylane.plist` |
| Redémarrer | `sudo launchctl kickstart -k system/com.polyskills.lightspeed-pennylane` |
| Voir les logs | fichiers dans `Idees/logs/service.out.log` et `service.err.log` |
| Modifier la config du service (avancé) | éditer `/Library/LaunchDaemons/com.polyskills.lightspeed-pennylane.plist` puis relancer bootstrap/kickstart ci-dessus |

## Sauvegarde des données

Les données comptables des clients vivent dans `Idees/data/clients/`
(référentiels + historique des conversions, fichiers source et générés).
**Ce dossier n'est pas versionné dans git** (données sensibles) — mettez en
place une sauvegarde régulière de ce dossier (Time Machine, copie planifiée
via `launchd`/`cron`, etc.), il n'existe nulle part ailleurs.

## Sécuriser l'accès

⚠️ Tel quel, l'application n'a **aucune authentification** : quiconque
accède à l'URL du Mac voit tous les clients. Pour un accès réseau partagé,
envisager au minimum l'un de :
- restreindre l'accès réseau au port `8501` (pare-feu réseau / VLAN / VPN
  interne uniquement, pas d'exposition directe sur internet)
- mettre un reverse proxy (Caddy, nginx) devant l'application avec
  authentification (Basic Auth, SSO d'entreprise...) et HTTPS
- demander une évolution de l'application pour une authentification
  applicative native (comptes utilisateurs)

## Dépannage

**Le service ne démarre pas** : consulter `Idees/logs/service.err.log`, et
`sudo launchctl print system/com.polyskills.lightspeed-pennylane` (regarder
`last exit code`). Cause fréquente : port déjà utilisé par une autre
application (relancer l'installation avec `--port` sur un autre port), ou
dépendance manquante (relancer `sudo ./deploy/macos/update-service.sh`).

**Page inaccessible depuis un autre poste** : vérifier le pare-feu
applicatif macOS (Réglages Système > Réseau > Coupe-feu) — s'il est actif,
l'installation l'a normalement déjà configuré, sinon autoriser
`.venv/bin/python` manuellement ou via
`sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$(pwd)/.venv/bin/python"`.
Vérifier aussi qu'aucun pare-feu réseau (routeur, VLAN) ne bloque le port en
amont.

**python3 introuvable** : installer Python via Homebrew
(`brew install python@3.12`) ou depuis python.org, puis ouvrir un nouveau
Terminal avant de relancer le script.

**`sudo` obligatoire** : la création d'un LaunchDaemon système
(`/Library/LaunchDaemons/`) nécessite les droits administrateur — c'est
l'équivalent du "PowerShell en tant qu'administrateur" requis côté Windows.
