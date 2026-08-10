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
