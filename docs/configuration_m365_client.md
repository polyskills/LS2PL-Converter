# Configuration M365 côté client — pas à pas

Ce document est destiné à l'**administrateur M365 du client** (ou à
Polyskills en l'accompagnant) : il liste, dans l'ordre, tout ce qu'il faut
faire **dans le tenant Microsoft 365 du client** pour que l'application
puisse récupérer automatiquement les exports LightSpeed reçus par mail et
en extraire les pièces jointes, ainsi que les réglages correspondants à
saisir ensuite côté **LS2PL**.

Pour le fonctionnement détaillé du service une fois en place (identification
par adresse, gestion des échecs...), voir
**[fetch_mail.md](fetch_mail.md)**. Pour l'installation du service côté
serveur d'hébergement, voir
**[deploy/windows/README.md](../deploy/windows/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**
ou
**[deploy/macos/README.md](../deploy/macos/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**.

## Vue d'ensemble

Une seule application Azure AD, enregistrée en **multi-tenant** et
possédée par **Polyskills**, sert pour tous les clients. Rien à créer côté
client sur ce point : le client se contente d'y **consentir**. En
revanche, la **boîte mail interrogée** (et les adresses d'envoi
LightSpeed) vivent bien dans le **tenant du client**, pas chez Polyskills.

Quatre étapes côté client :

1. Récupérer l'**ID du tenant** M365 du client.
2. Créer la (ou les) **boîte(s) mail** qui recevront les exports LightSpeed.
3. Donner le **consentement administrateur** à l'app Polyskills sur ces
   boîtes.
4. Configurer **LightSpeed** pour envoyer l'export comptable automatique
   vers l'adresse dédiée de chaque point de vente.

Chaque étape est suivie du réglage correspondant à saisir dans LS2PL.

---

## 1. Récupérer l'ID du tenant M365 du client

Dans le portail **Entra ID** (anciennement Azure AD) du client
(`https://entra.microsoft.com`, ou `portal.azure.com` > Microsoft Entra
ID) :

- **Vue d'ensemble** (Overview) → copier l'**ID de locataire** (*Tenant
  ID*), un GUID du type `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.

Seul un compte disposant d'un rôle **administrateur** sur ce tenant peut
effectuer les étapes suivantes (consentement admin en particulier).

➡️ **Dans LS2PL** : page **Réglages** → onglet **Gestion Email** → champ
**« Tenant ID Azure AD du client »**.

---

## 2. Créer la boîte mail à interroger

Deux organisations possibles, à choisir selon la taille du client :

- **Une boîte partagée unique** pour tous les points de vente (ex.
  `rapports-ls@<domaine-client>.fr`), qui recevra les exports de *tous*
  les points de vente — c'est elle que le service ira interroger, et
  c'est le **destinataire** de chaque mail qui permettra ensuite de
  distinguer les points de vente entre eux (voir étape 4).
- **Une boîte dédiée par point de vente** si le client préfère cloisonner
  (ex. `rapport_ls_paris_bar@<domaine-client>.fr`,
  `rapport_ls_valence@<domaine-client>.fr`...). Dans ce cas, une seule de
  ces boîtes doit être désignée comme boîte à interroger par le service —
  ou alors ces adresses doivent toutes exister comme **alias** d'une même
  boîte, interrogée seule.

Dans les deux cas, le point clé est : **l'adresse d'envoi configurée dans
LightSpeed peut être une adresse dédiée par point de vente, différente de
la boîte réellement interrogée**, du moment que cette adresse est un
**alias** de la boîte interrogée (ou en est le destinataire direct). C'est
ce qui permet à `core.email_ingest` d'identifier le point de vente sans
avoir à ouvrir plusieurs boîtes.

Recommandation la plus simple pour un nouveau client : **une seule boîte
partagée**, avec un **alias par point de vente** (`Admin centre
d'administration Microsoft 365` → **Groupes** → **Boîtes partagées** →
créer la boîte, puis onglet **Alias e-mail** pour ajouter une adresse par
point de vente). Aucune licence Exchange payante n'est nécessaire pour une
boîte partagée standard (sous réserve de taille/usage raisonnable).

➡️ **Dans LS2PL** : page **Réglages** → onglet **Gestion Email** → champ
**« Boîte mail à interroger (UPN) »** — l'adresse de la boîte **réellement
interrogée** (celle du service), pas forcément celle affichée à
LightSpeed si des alias sont utilisés.

---

## 3. Donner le consentement administrateur à l'app Polyskills

L'app Azure AD Polyskills demande deux permissions **applicatives**
Microsoft Graph (accès à la boîte sans utilisateur connecté, adaptées à un
service automatisé) : `Mail.Read` et `Mail.Send`.

Un administrateur du tenant client doit se rendre sur l'URL de
consentement admin suivante (remplacer `<TENANT_ID_CLIENT>` par l'ID
récupéré à l'étape 1, et `<APP_ID_POLYSKILLS>` par l'identifiant
d'application — *Application (client) ID* — de l'app Azure AD Polyskills,
fourni par Polyskills) :

```
https://login.microsoftonline.com/<TENANT_ID_CLIENT>/adminconsent?client_id=<APP_ID_POLYSKILLS>
```

En s'y connectant avec un compte **administrateur** de ce tenant, une page
Microsoft récapitule les permissions demandées (`Mail.Read`, `Mail.Send`)
et propose d'**accepter au nom de l'organisation**. Une fois accepté,
l'app Polyskills peut obtenir un jeton d'accès pour ce tenant — c'est ce
consentement, combiné au Tenant ID renseigné dans LS2PL (étape 1), qui
autorise le service à lire/répondre sur la boîte du client.

⚠️ Sans licence/permission adéquate sur la boîte concernée (boîte partagée
standard incluse dans la plupart des forfaits M365 Business), le
consentement peut être accepté mais l'accès à la boîte échouera au premier
cycle — vérifier que la boîte créée à l'étape 2 existe bien avant cette
étape.

➡️ **Rien à saisir dans LS2PL à cette étape** — c'est un pré-requis
technique silencieux : sans lui, le champ Tenant ID renseigné à l'étape 1
ne permettra pas d'obtenir de jeton, et le fetch échouera pour ce client.

---

## 4. Configurer LightSpeed pour l'envoi automatique

Dans LightSpeed (paramétrage des exports comptables du point de vente
concerné), configurer l'envoi automatique périodique de l'export
comptable vers l'**adresse dédiée** de ce point de vente (alias créé à
l'étape 2, ou boîte dédiée). Une adresse par point de vente, jamais une
adresse partagée entre deux points de vente : c'est cette adresse qui
permet à LS2PL de distinguer les points de vente à la réception,
**jamais** le nom du fichier joint.

➡️ **Dans LS2PL** : page **Table de correspondance** → **Points de vente**
→ champ **`adresse_email`** du point de vente correspondant. C'est cette
correspondance (adresse → point de vente) qui identifie le point de vente
recevant réellement l'export ; toute adresse non reconnue déclenche une
**alerte interne** (mail marqué comme non identifié) au lieu d'une
conversion, par sécurité.

---

## Récapitulatif — qui fait quoi

| Étape | Où | Qui | Réglage LS2PL correspondant |
|---|---|---|---|
| 1. Récupérer le Tenant ID | Entra ID du client | Admin client | Réglages → Gestion Email → *Tenant ID Azure AD du client* |
| 2. Créer la boîte (+ alias par PDV) | Centre d'admin M365 du client | Admin client | Réglages → Gestion Email → *Boîte mail à interroger (UPN)* |
| 3. Consentement admin | URL `adminconsent` (portail Microsoft) | Admin client | — (pré-requis technique, pas de champ dédié) |
| 4. Envoi auto par point de vente | Paramétrage export LightSpeed | Client / Polyskills | Table de correspondance → Points de vente → *adresse_email* |

Une fois les quatre étapes faites pour un client et les réglages
enregistrés dans LS2PL, le service de fetch (installé côté serveur
d'hébergement — voir les README de déploiement) prend le relais
automatiquement au cycle suivant, sans autre action.

## Vérifier que ça fonctionne

- Envoyer un export LightSpeed réel (ou de test) vers l'adresse dédiée
  d'un point de vente et attendre le prochain cycle du service (intervalle
  par défaut : 5 minutes, réglable via `LSPENNYLANE_POLL_INTERVAL_SECONDS`
  côté serveur).
- Succès attendu : un mail de réponse avec le fichier source, le CSV
  Pennylane généré et un récapitulatif, à l'adresse d'origine ; la
  conversion apparaît aussi dans l'historique du client (page
  Convertisseur).
- En cas d'échec (adresse non reconnue, mapping manquant, fichier
  illisible...) : une alerte part vers l'adresse interne de supervision
  (`LSPENNYLANE_ALERTE_INTERNE`, réglée côté serveur), jamais de fichier
  erroné envoyé au client. Voir [fetch_mail.md](fetch_mail.md) pour le
  détail du comportement en cas d'échec.

⚠️ Comme rappelé dans `fetch_mail.md`, ce parcours n'a pas encore été
validé en conditions réelles avec un vrai tenant client à la date de
rédaction — ce document décrit la configuration attendue à partir du code
et de l'architecture en place ; le premier essai réel doit être suivi
attentivement.
