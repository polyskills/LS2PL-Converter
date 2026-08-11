# Convertisseur LightSpeed → Pennylane

Application web (Streamlit) qui importe un export comptable **LightSpeed**
(`.xls`/`.xlsx`/`.csv`), le convertit en fichier **CSV d'import avancé
Pennylane**, et contrôle que le chiffre d'affaires n'a pas été altéré
pendant la conversion. Gère plusieurs clients, chacun avec son propre
référentiel et son propre historique.

LightSpeed ne gère pas de code analytique. L'application le **reconstitue**
à partir de deux informations disponibles pour chaque écriture : le
**compte comptable** de vente (déduit de la catégorie LightSpeed) et le
**point de vente** (choisi à l'import, un fichier = un point de vente). Le
couple (compte, point de vente) est ensuite recherché dans une table pour
produire la **famille** et le **code analytique** attendus par Pennylane.

## Fonctionnement

1. **Clients** (`pages/0_👥_Clients.py`) : chaque client dispose d'un espace
   isolé (référentiel + historique). Aucune authentification à ce stade
   (usage interne, équipe restreinte) — à durcir avant tout accès externe.
2. **Import** (`app.py`) : dépose d'un ou plusieurs fichiers export
   LightSpeed pour le client sélectionné. Chaque fichier est parsé
   (catégories de vente avec un nombre *variable* de taux de TVA, modes de
   paiement, report éventuel de la veille). Un contrôle de premier niveau,
   **indépendant du mapping comptable**, vérifie que le total des ventes
   TTC déclaré correspond au total des encaissements.
3. **Conversion** (`core/converter.py`) : chaque catégorie vendue devient une
   ligne de crédit sur le compte de vente mappé, avec sa famille et son code
   analytique ; la TVA collectée est cumulée par taux ; chaque mode de
   paiement devient une ligne de débit sur son compte de contrepartie ; un
   écart éventuel (report d'encaissement de la veille) est neutralisé sur un
   compte d'attente dédié pour garantir une écriture équilibrée.
4. **Contrôle** : le CA HT du fichier source et celui du fichier généré sont
   comparés (doivent être strictement égaux), de même que le total débit et
   le total crédit. **Toute catégorie, tout mode de paiement ou toute
   combinaison (compte, point de vente) non mappée bloque l'export** —
   aucune ligne n'est jamais ignorée silencieusement.
5. **Export** (`core/pennylane_export.py`) : génération du fichier `.csv`
   au format d'import avancé Pennylane (mêmes 18 colonnes que le modèle
   officiel), téléchargeable depuis l'interface.
6. **Historique** (`pages/2_🕓_Historique.py`, `core/history_store.py`) :
   **chaque tentative de conversion est archivée**, réussie ou non — fichier
   source, fichier généré, statut (OK / AVERTISSEMENT / ERREUR), indicateurs
   de contrôle, avertissements et erreurs. Détection informative des jours
   sans conversion enregistrée pour un point de vente donné.

## Tables de correspondance (page « Table de correspondance »)

Toutes les règles métier sont éditables dans l'interface (pas de valeur en
dur dans le code), propres à chaque client, persistées dans
`data/clients/<client_id>/mappings.json` :

- **Points de vente** : liste des sites/points de vente du client.
- **Comptes de vente** : catégorie LightSpeed → compte général Pennylane.
- **Codes analytiques** : (compte comptable, point de vente) → famille +
  code analytique.
- **Contreparties de paiement** : mode de paiement LightSpeed → compte de
  banque/caisse/créance plateforme.
- **TVA collectée** : taux de TVA → compte de TVA collectée.
- **Paramètres généraux** : code journal, code pays, compte d'écart
  utilisé pour équilibrer un éventuel report d'encaissement, etc.

Un jeu d'exemple (repris de la logique du fichier « Patch Lightspeed vers
Pennylane » transmis) peut être injecté à la création d'un client, à des
fins de test uniquement — à revalider intégralement avec le plan comptable
réel avant toute mise en production.

## Mise en route — checklist avant utilisation en production

Rien n'est utilisable tel quel pour un client réel sans ces étapes :

### 1. Référentiel comptable (obligatoire, par client)

Page **Table de correspondance**, à valider avec le plan comptable réel du
client (les valeurs pré-remplies via « référentiel d'exemple » sont
purement indicatives — comptes 511100/530000/445711.../etc. n'ont aucune
valeur réelle) :

- [ ] **Points de vente** : un par site/salle/activité réellement facturé
- [ ] **Comptes de vente** : une ligne par catégorie LightSpeed *effectivement
  rencontrée* dans les exports du client (sinon la conversion sera bloquée
  dès la première catégorie absente)
- [ ] **Codes analytiques** : une ligne par combinaison (compte, point de
  vente) réellement utilisée
- [ ] **Contreparties de paiement** : une ligne par mode de paiement
  LightSpeed du client (Carte bleue, Espèces, Deliveroo, UberEats,
  Lightspeed Payments...)
- [ ] **TVA collectée** : un compte par taux de TVA effectivement pratiqué
- [ ] **Paramètres généraux** : code journal, compte d'écart/report

Tant qu'une catégorie/mode de paiement/combinaison analytique manque, la
conversion **bloque volontairement** l'export (jamais de perte silencieuse)
— voir les avertissements/erreurs affichés à l'écran ou dans l'historique.

### 2. Fetch mail automatique (optionnel, par client)

Uniquement nécessaire si le client veut recevoir la conversion sans passer
par un import manuel. Détail complet des étapes Azure AD et du service
Windows dans **[deploy/windows/README.md](deploy/windows/README.md#service-de-fetch-automatique-des-exports-lightspeed-par-mail-optionnel)**.
En résumé :

- [ ] Une adresse mail dédiée par point de vente, créée côté client
  (ex. `rapport_ls_<site>_<pdv>@<domaine-client>`), configurée dans
  **LightSpeed** pour recevoir l'export comptable automatique
- [ ] Cette adresse renseignée dans le champ **adresse_email** du point de
  vente correspondant (page Table de correspondance) — c'est elle qui
  identifie client + point de vente à la réception, jamais le nom de fichier
- [ ] Le **tenant ID** M365 du client + la **boîte mail** à interroger
  renseignés page **Clients** (la boîte vit chez le client, pas chez
  Polyskills)
- [ ] Le **consentement admin** du client donné sur l'app Azure AD
  multi-tenant de Polyskills (permissions Graph `Mail.Read` + `Mail.Send`)
- [ ] Les variables d'environnement du service (`LSPENNYLANE_AZURE_CLIENT_ID`,
  `LSPENNYLANE_AZURE_CLIENT_SECRET`, `LSPENNYLANE_ALERTE_INTERNE`) définies
  sur le serveur avant d'installer `install-email-poller-service.ps1`

⚠️ Non testé à ce stade en conditions réelles (pas encore d'accès à un vrai
tenant client) — seule la logique de routage/conversion/non-envoi-en-cas-
d'échec est couverte par les tests (`tests/test_email_poller.py`). Un
premier essai réel avec le client Paris reste à faire dès le consentement
admin obtenu.

## Persistance et confidentialité

Pas de base de données : chaque client a son dossier sous
`data/clients/<client_id>/` (référentiel + fichiers archivés + journal
JSON Lines des conversions). Ce dossier est exclu du dépôt git
(`.gitignore`) car il contient des données comptables/financières réelles.
Sur un serveur dédié, prévoir un disque persistant avec sauvegarde
régulière pointant vers ce dossier — voir `data/README.md`.

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déploiement en serveur partagé (équipe, disque persistant)

Pour un hébergement central accessible à toute l'équipe via navigateur,
avec un vrai disque persistant (contrairement à Streamlit Community
Cloud) : voir **[deploy/windows/README.md](deploy/windows/README.md)**
(installation en service Windows via NSSM — démarrage automatique,
redémarrage sur plantage, mise à jour et désinstallation scriptées).

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

Les tests couvrent le parsing d'exports LightSpeed reconstitués (dont un
avec un nombre variable de colonnes de TVA, comme observé sur un vrai
fichier client), la conservation du CA lors de la conversion, l'équilibrage
débit/crédit (y compris avec report de la veille), et le blocage strict en
cas de mapping manquant (catégorie, point de vente ou mode de paiement).

## Limites connues à ce stade

- **Aucune authentification** : tout utilisateur de l'app voit tous les
  clients. À corriger avant tout accès par des personnes extérieures à
  l'équipe interne.
- **Historique fichier, pas de base de données** : suffisant pour un usage
  ponctuel/petite équipe ; à faire évoluer vers une vraie base si le volume
  de conversions ou les besoins de recherche/reporting augmentent.
- Les comptes par défaut proposés à titre d'exemple (511100, 530000,
  445711/445712...) n'ont aucune valeur comptable réelle et doivent être
  saisis/validés par client.
