# Fetch automatique des exports LightSpeed par mail

Fonctionnement détaillé de la réception automatique — en complément de la
checklist de mise en route ([mise_en_route.md](mise_en_route.md)), du
pas-à-pas de configuration du tenant M365 du client
([configuration_m365_client.md](configuration_m365_client.md)) et des
commandes d'installation du service
([deploy/windows/README.md](../deploy/windows/README.md),
[deploy/macos/README.md](../deploy/macos/README.md) ou
[deploy/linux/README.md](../deploy/linux/README.md) selon l'OS d'hébergement).

## Pourquoi

Sans ce service, chaque export LightSpeed doit être déposé manuellement
dans la page Convertisseur. Avec, l'export reçu par mail est identifié,
converti et renvoyé automatiquement, sans intervention.

## Principe : identifier par l'adresse, pas par le nom de fichier

Chaque **point de vente** d'un client peut avoir **deux** adresses mail
dédiées, sur la même boîte (page Table de correspondance) :

| Champ | Ce qui y arrive | Traitement |
|---|---|---|
| `adresse_email` | export comptable | conversion vers Pennylane |
| `adresse_email_consolidation` | rapports Tickets et Transactions | consolidation du CA |

LightSpeed est configuré pour envoyer chaque export à l'adresse qui lui
correspond. À la réception :

1. l'adresse **destinataire** du mail suffit à elle seule à retrouver
   **client, point de vente ET traitement visé**
   (`core.mapping_store.find_client_pdv_par_adresse`) ;
2. le **nom de fichier** ne sert qu'à extraire la **période couverte**
   (`core.email_ingest.extraire_periode`), pour pré-remplir la date de
   pièce — jamais à identifier le client, moins fiable.

⚠️ Quand une même boîte reçoit plusieurs adresses dédiées via des **alias**
(cas courant : une boîte partagée unique + un alias par point de vente,
recommandé dans `docs/configuration_m365_client.md`), le champ `toRecipients`
restitué par Microsoft Graph est **résolu contre l'annuaire** et peut donc
être normalisé vers l'adresse **principale** de la boîte, perdant l'alias
réellement utilisé par l'expéditeur. `core.email_poller._adresses_destinataires`
contourne ce piège en lisant d'abord l'en-tête RFC5322 `To:` **brut**
(`internetMessageHeaders`, jamais réécrit en transit), avec repli sur
`toRecipients` si cet en-tête est absent.

C'est délibéré : une adresse mal configurée déclenche une alerte interne
immédiate (adresse inconnue), alors qu'un nom de fichier mal interprété
aurait pu convertir silencieusement sur le mauvais référentiel — ou, depuis
l'arrivée de la consolidation, envoyer un export comptable dans la mauvaise
moulinette.

## Consolidation : deux rapports, deux messages

Une consolidation a besoin des rapports **Tickets** et **Transactions** d'une
même période, et Lightspeed les envoie dans **deux messages distincts**. Le
poller ne peut donc pas produire un résultat dès le premier message.

Le premier rapport arrivé est rangé dans un **sas d'attente**
(`core/consolidation_sas.py`, sous `data/clients/<id>/consolidations/en_attente/`)
et son message est marqué lu comme d'habitude. La consolidation se déclenche
à l'arrivée du binôme, puis le sas est vidé.

- **Clé d'appariement** : `(point de vente, date de début, date de fin)`. Le
  point de vente vient de l'adresse, la période du nom de fichier
  (`..._AAAAMMJJ_AAAAMMJJ.xls`). Jamais de l'heure d'arrivée, qui ne prouve
  rien. Deux journées peuvent donc attendre en parallèle sans se mélanger.
- **Quel rapport** est déterminé par le nom de fichier (`_tickets_` /
  `_transactions_`) — c'est le seul rôle du nom ici, les deux rapports
  arrivant sur la même adresse. Une interversion serait de toute façon
  rattrapée par le contrôle de colonnes à la lecture.
- **L'ordre d'arrivée est indifférent**, et un renvoi du même rapport
  remplace le précédent (c'est presque toujours une correction).
- **Un rapport resté seul plus de 4 h déclenche une alerte interne**, une
  seule fois — un export qui ne part plus côté Lightspeed ne doit pas passer
  inaperçu, la consolidation se contentant sinon de ne jamais se déclencher.
  Le rapport reçu est conservé : un envoi tardif complète encore la paire.
  Au-delà de 7 jours, il est abandonné.
- **Le site de consolidation** (BAR / RESTAURANT) doit être renseigné sur le
  point de vente : il fixe les périodes de service. S'il manque, la paire
  **reste dans le sas** et un échec est signalé — jamais de perte, jamais de
  repli silencieux sur un site deviné.
- **Une paire complète en échec est retentée à chaque cycle.** La cause se
  corrige presque toujours dans la Table de correspondance, jamais dans le
  sas : dès qu'elle l'est, la consolidation repart seule, sans qu'un nouveau
  rapport ait à arriver. Le motif du dernier échec est mémorisé et la
  notification n'est envoyée qu'à son changement, pour ne pas répéter le même
  message à chaque passage. La page Consolidation liste ces paires et offre un
  bouton « Relancer » pour ne pas attendre le cycle suivant.

L'attente est visible page Consolidation, dans le panneau « rapports reçus par
mail, en attente de leur binôme ».

## Où vivent les boîtes mail

Les boîtes mail — et l'app Azure AD elle-même (permissions applicatives
Graph `Mail.ReadWrite` + `Mail.Send`) — vivent dans le **tenant M365 du
client** : c'est le `tenant_id` renseigné par client (page Réglages) qui
détermine quelle autorité Azure AD émet le jeton d'accès. Le client donne,
une fois, son **consentement admin** à cette app sur son propre tenant
(bouton *Grant admin consent*, l'app étant enregistrée en son sein — pas
de flux de consentement externe). Voir
[configuration_m365_client.md](configuration_m365_client.md) pour le
pas-à-pas complet, création de l'app comprise.

## Déroulé d'un cycle (`core/email_poller.py`)

Pour chaque client ayant un tenant + une boîte mail configurés :

1. liste les mails non lus avec pièce jointe de la boîte ;
2. pour chaque pièce jointe reconnue (`.xls`/`.xlsx`/`.csv`) :
   - adresse destinataire inconnue → **alerte interne**, mail marqué lu ;
   - adresse connue → parse + convertit avec le référentiel du client
     identifié, **exactement le même moteur** que l'import manuel
     (`core.lightspeed_parser` → `core.converter` → `core.pennylane_export`) ;
   - la tentative est **archivée dans l'historique** du client, succès ou
     échec ;
   - succès → réponse avec fichier source + CSV généré et un récapitulatif,
     envoyée à l'adresse **résultat** du point de vente si elle est
     configurée (champ `adresse_resultat`, page Table de correspondance),
     sinon à l'adresse de réception d'origine (comportement par défaut) ;
   - échec (mapping manquant, fichier illisible...) → **alerte interne
     uniquement**, jamais de fichier erroné envoyé au client ;
3. le mail source est marqué lu.

## Composants

| Fichier | Rôle |
|---|---|
| `core/graph_client.py` | Client HTTP minimal Microsoft Graph, authentification "application" (msal) |
| `core/email_ingest.py` | Identification déterministe (adresse → client/pdv, nom de fichier → période) |
| `core/email_poller.py` | Orchestration d'un cycle, testable sans réseau (faux client Graph) |
| `email_poller.py` | Point d'entrée : boucle infinie + intervalle, à déployer en service (Windows/macOS/Linux) |
| `tests/test_email_poller.py` | Cas nominal, adresse inconnue, mapping manquant, client sans fetch configuré |

## État actuel

✅ **Éprouvé en conditions réelles le 11/09/2026** : premier cycle sur un tenant
client, avec conversion comptable et consolidation menées à bien. Le seul
incident rencontré a été une conversion bloquée sur un mapping manquant —
c'est-à-dire le comportement attendu, l'outil refusant de convertir sur un
compte non paramétré plutôt que d'approximer. Le traitement est reparti seul
après complétion de la table de correspondance.

Un défaut a été corrigé à cette occasion : le champ « Adresse d'alerte interne »
n'était pas découpé, et deux adresses séparées par une virgule partaient en bloc
à Microsoft Graph, qui rejetait l'envoi (`ErrorInvalidRecipients`). L'alerte
était donc perdue — avec, en même temps, le signal de l'incident qu'elle
transportait. Corrigé en v1.2.
