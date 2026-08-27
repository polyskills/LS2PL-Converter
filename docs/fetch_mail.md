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

Chaque **point de vente** d'un client peut avoir sa propre adresse mail
dédiée (champ `adresse_email`, page Table de correspondance). LightSpeed
est configuré pour envoyer l'export comptable automatique de ce point de
vente à cette adresse. À la réception :

1. l'adresse **destinataire** du mail suffit à elle seule à retrouver
   **client + point de vente** (`core.mapping_store.find_client_pdv_by_email`) ;
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
aurait pu convertir silencieusement sur le mauvais référentiel.

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

⚠️ Non testé en conditions réelles (pas encore de tenant client ni de
consentement admin obtenu). La logique métier est couverte par les tests
automatisés, mais un premier essai réel reste à faire.
