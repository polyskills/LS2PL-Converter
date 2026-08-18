# Configuration M365 côté client — pas à pas

Ce document liste, dans l'ordre, tout ce qu'il faut faire **dans le tenant
Microsoft 365 du client** — création de l'application Azure AD comprise —
pour que l'application puisse récupérer automatiquement les exports
LightSpeed reçus par mail et en extraire les pièces jointes, ainsi que les
réglages correspondants à saisir ensuite côté **LS2PL**. Il permet de
suivre la procédure de bout en bout, y compris pour un premier test.

Pour le fonctionnement détaillé du service une fois en place (identification
par adresse, gestion des échecs...), voir
**[fetch_mail.md](fetch_mail.md)**. Pour l'installation du service côté
serveur d'hébergement, voir
**[deploy/windows/README.md](../deploy/windows/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**
ou
**[deploy/macos/README.md](../deploy/macos/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**.

## Vue d'ensemble

L'application Azure AD est enregistrée **directement dans le tenant M365
du client** (application **single tenant**, pas multi-tenant) : pas d'URL
de consentement externe à faire valider par un tiers — l'admin du client
crée l'app dans son propre tenant et s'auto-accorde les permissions.
La **boîte mail interrogée** (et les adresses d'envoi LightSpeed) vivent
elles aussi dans ce même tenant.

Cinq étapes côté client :

0. Créer l'**application (App registration)** dans Entra ID du client.
1. Récupérer l'**ID du tenant** M365 du client.
2. Créer la (ou les) **boîte(s) mail** qui recevront les exports LightSpeed.
3. Donner le **consentement administrateur** sur les permissions de
   l'application.
4. Configurer **LightSpeed** pour envoyer l'export comptable automatique
   vers l'adresse dédiée de chaque point de vente.

Chaque étape est suivie du réglage correspondant à saisir dans LS2PL.

---

## 0. Créer l'application dans Entra ID du client

Dans le portail **Entra ID** (anciennement Azure AD) du client
(`https://entra.microsoft.com`), avec un compte **administrateur** de ce
tenant :

1. **Identités** → **Applications** → **Inscriptions d'applications**
   (*App registrations*) → **Nouvelle inscription** (*New registration*).
2. Nom de l'application : libre, par ex. `LS2PL - <nom du client>`.
3. **Types de comptes pris en charge** : choisir **« Comptes dans cet
   annuaire d'organisation uniquement »** (*single tenant* — l'app ne
   sert que ce client, pas besoin de multi-tenant).
4. **URI de redirection** : laisser vide — le service s'authentifie en
   flux **client credentials** (app-only), sans redirection navigateur.
5. **Inscrire** (*Register*).

Une fois créée, sur la page **Vue d'ensemble** de l'application, noter :

- l'**ID d'application (client)** (*Application (client) ID*) — un GUID ;
- l'**ID de l'annuaire (locataire)** (*Directory (tenant) ID*) — un autre
  GUID, identique à celui récupéré à l'étape 1.

Puis créer le secret d'authentification. ⚠️ Les étapes suivantes se font
dans le **sous-menu de gauche propre à la fiche de cette application**
(pas dans le menu général d'Entra ID) : rester sur la page de l'app
ouverte juste au-dessus (celle où figurent l'ID d'application et le
Tenant ID), et chercher **Certificats et secrets** dans son menu latéral,
entre *Authentification* et *Autorisations API* :

6. **Certificats et secrets** (*Certificates & secrets*) → onglet **Secrets
   client** → **Nouveau secret client** (*New client secret*) → donner une
   description et une expiration (24 mois par ex.), **Ajouter**.
7. Copier immédiatement la **valeur** (*Value*) du secret affichée — elle
   ne sera **plus jamais visible** ensuite (seul son identifiant restera
   affiché).

Enfin, déclarer les permissions Microsoft Graph nécessaires :

8. **Autorisations API** (*API permissions*) → **Ajouter une autorisation**
   (*Add a permission*) → **Microsoft Graph** → **Autorisations
   d'application** (*Application permissions* — pas *Delegated*, le
   service tourne sans utilisateur connecté) → cocher `Mail.ReadWrite` et
   `Mail.Send` → **Ajouter des autorisations**.
   ⚠️ Bien `Mail.ReadWrite`, pas `Mail.Read` seul : le service doit pouvoir
   marquer les mails traités comme lus (`PATCH` sur le message), une
   opération d'écriture que `Mail.Read` seul refuse (HTTP 403
   `ErrorAccessDenied`).

L'étape de consentement (bouton *Grant admin consent*) se fait juste
après, à l'étape 3 ci-dessous, une fois la boîte mail créée.

➡️ **Dans LS2PL** : page **Réglages** → onglet **Gestion Email** → section
**« App Azure AD de ce client »** → champs **« ID d'application »** et
**« Secret client »**. C'est la voie recommandée depuis qu'une app est créée
par client (plutôt que les variables d'environnement globales
`LSPENNYLANE_AZURE_CLIENT_ID`/`_SECRET` du service installé côté serveur,
qui ne fonctionnent que pour un seul client à la fois — conservées comme
repli si laissées vides ici). Le **Tenant ID**, lui, se saisit dans le même
onglet, champ « Tenant ID Azure AD du client » (étape 1 ci-dessous).

---

## 1. Récupérer l'ID du tenant M365 du client

Déjà noté à l'étape précédente (*Directory (tenant) ID*), mais aussi
consultable indépendamment sur Entra ID → **Vue d'ensemble** (*Overview*)
→ **ID de locataire** (*Tenant ID*), un GUID du type
`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`.

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
point de vente).

**Aucune licence n'est nécessaire** : une boîte partagée standard est
gratuite (stockage par défaut ~50 Go, largement suffisant pour des
exports comptables), et l'accès utilisé ici est en **permissions
applicatives** Graph (authentification "application", sans utilisateur
connecté) — ce mode ne dépend jamais d'une licence sur la boîte ciblée,
contrairement à un accès délégué (au nom d'un utilisateur) qui lui
suppose une licence Exchange sur ce compte.

⚠️ Seul point de vigilance possible, sans lien avec la licence : si le
tenant du client a mis en place une **Application Access Policy**
Exchange (restriction du périmètre de boîtes accessible en accès
applicatif — rare sur un tenant PME standard, plus fréquent sur un tenant
durci), l'admin du client doit explicitement y inclure la boîte créée ici
(`New-ApplicationAccessPolicy` en PowerShell Exchange Online), en plus du
consentement admin de l'étape 3. Symptôme si c'est le cas : consentement
accepté mais échec d'accès à la boîte au premier cycle du service.

➡️ **Dans LS2PL** : page **Réglages** → onglet **Gestion Email** → champ
**« Boîte mail à interroger (UPN) »** — l'adresse de la boîte **réellement
interrogée** (celle du service), pas forcément celle affichée à
LightSpeed si des alias sont utilisés.

---

## 3. Donner le consentement administrateur

L'application demande deux permissions **applicatives** Microsoft Graph
(accès à la boîte sans utilisateur connecté, adaptées à un service
automatisé) : `Mail.ReadWrite` et `Mail.Send`, déclarées à l'étape 0.

L'app étant enregistrée dans le tenant du client (single-tenant), pas
besoin d'URL de consentement externe : sur la page de l'application →
**Autorisations API** (*API permissions*), un administrateur du tenant
clique directement sur **Accorder un consentement d'administrateur pour
`<nom du tenant>`** (*Grant admin consent for `<tenant>`*), puis confirme.
Les deux permissions passent au statut **Accordé** (*Granted*) — c'est ce
consentement, combiné à l'ID d'application/secret/Tenant ID saisis dans
LS2PL (étapes 0 et 1), qui autorise le service à lire/répondre sur la
boîte du client.

⚠️ Le consentement peut être accordé alors que la boîte créée à l'étape 2
n'existe pas encore (ou n'est pas propagée) — vérifier son existence avant
de tester. Aucune licence n'est en cause ici (voir étape 2) : un échec
d'accès malgré un consentement accordé vient plutôt d'une éventuelle
Application Access Policy Exchange restrictive côté client (voir étape 2).

➡️ **Rien à saisir dans LS2PL à cette étape** — c'est un pré-requis
technique : sans lui, le service ne pourra pas obtenir de jeton, et le
fetch échouera pour ce client.

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
| 0. Créer l'application | Entra ID du client → App registrations | Admin client | Réglages → Gestion Email → *ID d'application* / *Secret client* |
| 1. Récupérer le Tenant ID | Entra ID du client | Admin client | Réglages → Gestion Email → *Tenant ID Azure AD du client* |
| 2. Créer la boîte (+ alias par PDV) | Centre d'admin M365 du client | Admin client | Réglages → Gestion Email → *Boîte mail à interroger (UPN)* |
| 3. Consentement admin | Page de l'app → API permissions → Grant admin consent | Admin client | — (pré-requis technique, pas de champ dédié) |
| 4. Envoi auto par point de vente | Paramétrage export LightSpeed | Client / Polyskills | Table de correspondance → Points de vente → *adresse_email* |

Une fois ces cinq étapes faites pour un client, les réglages saisis dans
LS2PL, et le service (côté serveur d'hébergement — voir les README de
déploiement) configuré avec l'ID d'application et le secret de l'étape 0,
le fetch automatique prend le relais au cycle suivant, sans autre action.

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
