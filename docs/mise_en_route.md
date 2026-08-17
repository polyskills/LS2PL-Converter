# Mise en route — checklist avant utilisation en production

Rien n'est utilisable tel quel pour un client réel sans ces étapes :

## 1. Référentiel comptable (obligatoire, par client)

Page **Table de correspondance**, à valider avec le plan comptable réel du
client (les valeurs pré-remplies via « référentiel d'exemple » sont
purement indicatives — comptes 511100/530000/445711.../etc. n'ont aucune
valeur réelle) :

- [ ] **Points de vente** : un par site/salle/activité réellement facturé
- [ ] **Comptes de vente** : le référentiel des comptes de vente Pennylane
  utilisés (sert de liste de choix aux deux tables suivantes)
- [ ] **Départements LightSpeed** : une ligne par département LightSpeed
  *effectivement rencontré* dans les exports du client, avec son compte de
  vente choisi (sinon la conversion sera bloquée dès le premier département
  sans compte)
- [ ] **Codes analytiques** : une ligne par combinaison (compte, point de
  vente, département) réellement utilisée
- [ ] **Contreparties de paiement** : une ligne par mode de paiement
  LightSpeed du client (Carte bleue, Espèces, Deliveroo, UberEats,
  Lightspeed Payments...)
- [ ] **TVA collectée** : un compte par taux de TVA effectivement pratiqué
- [ ] **Paramètres généraux** (page Réglages) : code journal, compte
  d'écart/report

Tant qu'une catégorie/mode de paiement/combinaison analytique manque, la
conversion **bloque volontairement** l'export (jamais de perte silencieuse)
— voir les avertissements/erreurs affichés à l'écran ou dans l'historique.

## 2. Fetch mail automatique (optionnel, par client)

Uniquement nécessaire si le client veut recevoir la conversion sans passer
par un import manuel. Voir **[fetch_mail.md](fetch_mail.md)** pour le
fonctionnement détaillé, **[configuration_m365_client.md](configuration_m365_client.md)**
pour le pas-à-pas complet côté tenant M365 du client (Tenant ID, boîte
mail, consentement admin, LightSpeed), et selon l'OS d'hébergement,
**[deploy/windows/README.md](../deploy/windows/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**
ou
**[deploy/macos/README.md](../deploy/macos/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**
pour l'installation du service. En résumé :

- [ ] Une adresse mail dédiée par point de vente, créée côté client
  (ex. `rapport_ls_<site>_<pdv>@<domaine-client>`), configurée dans
  **LightSpeed** pour recevoir l'export comptable automatique
- [ ] Cette adresse renseignée dans le champ **adresse_email** du point de
  vente correspondant (page Table de correspondance) — c'est elle qui
  identifie client + point de vente à la réception, jamais le nom de fichier
- [ ] Le **tenant ID** M365 du client + la **boîte mail** à interroger
  renseignés page **Réglages** (l'app Azure AD et la boîte vivent toutes
  deux chez le client)
- [ ] L'**app Azure AD créée dans le tenant du client** (pas Polyskills) et
  le **consentement admin** accordé sur ses permissions Graph
  (`Mail.ReadWrite` + `Mail.Send`) — voir
  [configuration_m365_client.md](configuration_m365_client.md) pour le
  pas-à-pas complet
- [ ] Les variables d'environnement du service (`LSPENNYLANE_AZURE_CLIENT_ID`,
  `LSPENNYLANE_AZURE_CLIENT_SECRET`, `LSPENNYLANE_ALERTE_INTERNE`) définies
  sur le serveur avant d'installer `install-email-poller-service.ps1`

⚠️ Non testé à ce stade en conditions réelles (pas encore d'accès à un vrai
tenant client) — seule la logique de routage/conversion/non-envoi-en-cas-
d'échec est couverte par les tests (`tests/test_email_poller.py`). Un
premier essai réel avec le client Paris reste à faire dès le consentement
admin obtenu.
