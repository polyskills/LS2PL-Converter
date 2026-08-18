# Déploiement sur serveur Windows (service, disque persistant)

Cette option héberge l'application en continu sur un serveur Windows
partagé, accessible à toute l'équipe via une URL réseau (`http://<serveur>:8501`).
Contrairement à Streamlit Community Cloud, **le disque est réellement
persistant** : le référentiel et l'historique de chaque client ne sont
plus perdus à chaque redémarrage.

## Prérequis

- Windows Server (2016+) ou Windows 10/11, avec droits administrateur
- [Python 3.10+](https://www.python.org/downloads/) installé et dans le PATH
  (`winget install Python.Python.3.12`, cocher "Add to PATH" si install manuelle)
- [Git](https://git-scm.com/download/win) installé
- Accès sortant à internet le temps de l'installation (téléchargement des
  dépendances Python et de NSSM)

## Installation (première fois)

Ouvrir **PowerShell en tant qu'administrateur**, puis :

```powershell
# 1. Cloner le dépôt à l'emplacement de votre choix
cd C:\Apps
git clone https://github.com/polyskills/Idees.git
cd Idees
git checkout claude/lightspeed-pennylane-converter-njmeyd

# 2. Lancer l'installation du service (Python, dépendances, NSSM, service, pare-feu)
.\deploy\windows\install-service.ps1
```

Le script :
1. vérifie Python et crée un environnement virtuel `.venv`
2. installe les dépendances (`requirements.txt`)
3. télécharge NSSM (gestionnaire de service Windows) s'il est absent
4. enregistre l'application comme service Windows (**démarrage automatique
   au boot, redémarrage automatique en cas de plantage**)
5. ouvre le port `8501` dans le pare-feu Windows

À la fin, l'application est accessible :
- en local sur le serveur : `http://localhost:8501`
- depuis le réseau : `http://<nom-ou-IP-du-serveur>:8501`

### Personnaliser le port ou le nom du service

```powershell
.\deploy\windows\install-service.ps1 -Port 8080 -ServiceName "LSPennylaneProd"
```

## Service de fetch automatique des exports LightSpeed par mail (optionnel)

En complément du service applicatif, `install-email-poller-service.ps1`
installe un second service Windows qui va chercher automatiquement les
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
3. Son **ID d'application** et son **secret client** renseignés dans LS2PL,
   page Réglages > Gestion Email (recommandé, un jeu d'identifiants par
   client) — ou, à défaut, en variables d'environnement **machine** (pas
   juste utilisateur, sans quoi le service ne les verrait pas au
   démarrage), utilisées en repli pour tout client sans identifiants
   propres :
   ```powershell
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_ID", "<app id>", "Machine")
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_SECRET", "<secret>", "Machine")
   ```
4. `LSPENNYLANE_ALERTE_INTERNE` (optionnelle, machine) : adresse recevant
   les alertes internes.
   ```powershell
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_ALERTE_INTERNE", "compta@polyskills.fr", "Machine")
   ```
5. Pour chaque client concerné : tenant ID + boîte mail renseignés page
   **Réglages**, et adresse mail dédiée sur chaque point de vente page
   **Table de correspondance**.

⚠️ Les variables d'environnement `LSPENNYLANE_AZURE_CLIENT_ID`/`_SECRET`
restent **globales au serveur**, donc communes à tous les clients qui n'ont
pas leurs propres identifiants renseignés dans Réglages — ce repli ne
fonctionne donc que tant qu'**un seul** client de ce serveur en dépend.
Pour plusieurs clients simultanément, renseigner l'ID/secret **propre à
chacun** dans Réglages > Gestion Email évite complètement cette limite.

Puis, dans le même PowerShell administrateur, après `install-service.ps1` :
```powershell
.\deploy\windows\install-email-poller-service.ps1
```

Ce service ne renvoie **jamais** de fichier au client en cas d'échec de
conversion (mapping manquant, fichier illisible...) — dans ce cas, seule
l'adresse `LSPENNYLANE_ALERTE_INTERNE` est notifiée, avec le détail de
l'erreur, pour correction manuelle du référentiel puis reprise via l'import
manuel habituel.

## Mettre à jour l'application

À chaque évolution du code (nouveau commit sur la branche) :

```powershell
cd C:\Apps\Idees
.\deploy\windows\update-service.ps1
```

Ce script arrête le service, récupère la dernière version (`git pull`),
réinstalle les dépendances si besoin, puis redémarre le service. Vérifiez
ensuite que le **hash de version** affiché dans le menu latéral de
l'application correspond bien au dernier commit sur GitHub.

## Désinstaller le service

```powershell
cd C:\Apps\Idees
.\deploy\windows\uninstall-service.ps1
```

Arrête et supprime le service ainsi que la règle de pare-feu. Le code, les
dépendances (`.venv`) et surtout **les données clients (`data\clients\`)
sont conservés** — seule la couche "service" est retirée.

## Administration courante

| Action | Commande |
|---|---|
| Voir le statut du service | `Get-Service LightspeedPennylane` |
| Arrêter | `Stop-Service LightspeedPennylane` |
| Démarrer | `Start-Service LightspeedPennylane` |
| Redémarrer | `Restart-Service LightspeedPennylane` |
| Voir les logs | fichiers dans `Idees\logs\service.out.log` et `service.err.log` |
| Modifier la config du service (avancé) | `.\deploy\windows\tools\nssm.exe edit LightspeedPennylane` (ouvre une interface graphique) |

## Sauvegarde des données

Les données comptables des clients vivent dans `Idees\data\clients\`
(référentiels + historique des conversions, fichiers source et générés).
**Ce dossier n'est pas versionné dans git** (données sensibles) — mettez en
place une sauvegarde régulière de ce dossier (copie planifiée, sauvegarde
Windows Server habituelle, etc.), il n'existe nulle part ailleurs.

## Sécuriser l'accès

⚠️ Tel quel, l'application n'a **aucune authentification** : quiconque
accède à l'URL du serveur voit tous les clients. Pour un accès réseau
partagé, envisager au minimum l'un de :
- restreindre l'accès réseau au port `8501` (pare-feu / VLAN / VPN
  interne uniquement, pas d'exposition directe sur internet)
- mettre un reverse proxy (IIS, nginx, Caddy) devant l'application avec
  authentification (Basic Auth, SSO d'entreprise...) et HTTPS
- demander une évolution de l'application pour une authentification
  applicative native (comptes utilisateurs)

## Dépannage

**Le service ne démarre pas** : consulter `Idees\logs\service.err.log`.
Cause fréquente : port déjà utilisé par une autre application (relancer
l'installation avec `-Port` sur un autre port), ou dépendance manquante
(relancer `.\deploy\windows\update-service.ps1`).

**Page inaccessible depuis un autre poste** : vérifier que le pare-feu
Windows du serveur autorise bien le port choisi (`Get-NetFirewallRule
-DisplayName "LightSpeed-Pennylane*"`), et que le réseau/VLAN n'a pas de
restriction supplémentaire en amont (pare-feu réseau, groupe de sécurité
cloud...).

**Python introuvable** : réinstaller Python en cochant "Add python.exe to
PATH", puis ouvrir un nouveau PowerShell avant de relancer le script.
