# Consolidation du CA par période de service

Croise les **deux rapports Lightspeed Back Office** (`.xls`, `.xlsx` ou `.csv`) d'une même période — le
rapport **Tickets** et le rapport **Transactions** — pour produire un classeur
Excel de synthèse de l'exploitation.

C'est un traitement **indépendant de la conversion comptable** : il ne consulte
pas la table de correspondance du client et ne produit aucune écriture
Pennylane. Les deux fonctions cohabitent simplement dans la même application,
avec le même client sélectionné.

## Ce que produit le classeur

| Onglet | Contenu |
|---|---|
| `SYNTHESE` | CA TTC/HT, part du total, couverts, CA Food, CA Bev et tables ouvertes par période — deux fois : période à l'**ouverture** de la table, puis au **règlement** |
| `JOUR x PERIODE` | CA TTC et couverts, jour par jour et période par période |
| `ROTATIONS` | Nombre d'ouvertures par table et par période, et moyenne par jour |
| `DUREE PRESENCE` | Répartition des durées ouverture → règlement par tranche, avec moyenne, minimum et maximum |
| `DONNEES` | Une ligne par ligne de transaction, prête pour vos propres `SUMIFS` |
| `TICKETS` | Une ligne par ticket |
| `ANOMALIES` | Contrôles et points à vérifier |

Les onglets de synthèse ne contiennent **que des formules** pointant vers
`DONNEES` et `TICKETS` : le classeur reste recalculable et vérifiable dans
Excel, ce n'est pas un rapport figé.

## Les règles de calcul

- **Le CA d'un ticket est la somme de toutes ses lignes de transaction**, tous
  types confondus (`SALE`, `SPLIT`, `UPDATE`, `TRANSFER`, `VOID`, `RECALL`,
  `FOREIGN`). Les types techniques se compensent entre eux et leur somme
  reconstitue exactement le total du ticket.
- **La période retenue est celle de l'ouverture de la table**, pas du
  règlement : une commande passée en Afterwork et encaissée en Soir compte en
  Afterwork. La déclinaison au règlement figure dans le second bloc de la
  feuille `SYNTHESE`.
- **Journée d'exploitation** : un ticket ouvert après minuit et avant 5h30 est
  rattaché à la veille.
- **Les couverts viennent des tickets** ; ceux d'un ticket annulé sont négatifs
  et annulent ceux du ticket repris.
- **Famille** = préfixe du groupe Lightspeed (`BEV`, `FOOD`, `DIV`), complété
  par une table de correspondance explicite pour les groupes sans préfixe
  normalisé (`Cocktail` → BEV, `Cuisine Chaud` → FOOD…). Un groupe inconnu
  tombe en `AUTRE` et **apparaît dans les anomalies** — jamais absorbé en
  silence.

## Les sites

Le site choisi à l'écran détermine les plages horaires :

| Site | Périodes |
|---|---|
| `BAR` | Bar Journée (5h30-16h59), Bar Afterwork (17h-18h59), Bar Soir (19h-21h59), Bar Nuit (22h-5h29) |
| `RESTAURANT` | Restaurant Midi (5h30-16h59), Restaurant Soir (17h-5h29) |

## Mode d'emploi

1. Sélectionner le client, puis ouvrir **Consolidation**.
2. Déposer les exports. **Plusieurs jours peuvent être traités d'un coup** :
   déposez tous les rapports, les doublons sont éliminés par identifiant.
3. Vérifier la répartition Tickets / Transactions. Elle est pré-remplie
   d'après le nom des fichiers (`..._tickets_...` / `..._transactions_...`) et
   reste corrigeable si un export a été renommé.
4. Choisir le site, puis lancer la consolidation.
5. Contrôler l'indicateur **« Contrôle transactions / tickets »** avant
   d'exploiter le classeur (voir ci-dessous), puis télécharger.

Le site est **pré-sélectionné d'après le nom des fichiers** quand celui-ci le
permet (`..._barutopic_...` → BAR) ; il reste corrigeable, et c'est la valeur
affichée — jamais le nom de fichier — qui détermine le calcul.

Chaque consolidation est archivée automatiquement, avec ses rapports source et
le classeur produit, dans la page **Historique** rangée sous **Consolidation**. Ce stockage est
entièrement séparé de celui des conversions comptables
(`data/clients/<id>/consolidations/` contre `data/clients/<id>/history/`) :
chacun a son journal, son plafond de conservation et sa purge. Aucun des deux
traitements ne peut faire perdre les données de l'autre.

## Une journée sans vente

Un jour de fermeture, LightSpeed produit quand même ses deux rapports, **vides**.
Ce n'est pas une anomalie : la consolidation aboutit, avec des totaux à zéro, et
la journée est signalée explicitement — ligne « Aucune vente sur la période »
dans l'onglet `ANOMALIES`, mention dans le mail de résultat (dont l'objet se
termine par « sans vente ») et bandeau à l'écran.

La période vient alors du **nom du fichier**, le contenu ne pouvant plus dire de
quelle journée il s'agit.

Si une journée signalée ainsi aurait dû être ouverte, le problème est en amont :
c'est l'export LightSpeed qu'il faut vérifier, pas la consolidation.

## Le contrôle qui compte

L'écart entre le total des lignes de transaction et le total des tickets doit
être **nul**. C'est le seul contrôle qui invalide le classeur : un écart non
nul signifie presque toujours que les deux rapports ne couvrent pas exactement
la même période. Le classeur est tout de même produit — pour permettre le
diagnostic — mais ses totaux ne sont pas exploitables en l'état.

Les autres lignes de l'onglet `ANOMALIES` sont de deux natures.

**Des points à vérifier**, signalés à l'écran et dans le mail de résultat, qui
n'empêchent pas d'utiliser le classeur : groupes non mappés (famille `AUTRE`),
tickets annulés.

**Des informations**, qui ne sont ni signalées ni comptées comme anomalies :

- l'**écart transactions/tickets**, déjà affiché en indicateur ;
- les **tickets rattachés à leur période d'ouverture** et non au profil
  Lightspeed de clôture. Toute table ouverte avant une frontière de période et
  réglée après en fait partie — 9 tickets sur 23 sur une journée réelle, autant
  dire tous les jours dans un bar. C'est la règle de calcul assumée de l'outil,
  pas un défaut. La ligne reste dans le classeur parce qu'elle explique
  précisément pourquoi une répartition par période peut différer de celle d'un
  rapport Lightspeed natif, mais elle ne déclenche aucune alerte.

## Réception automatique par mail

Les deux rapports peuvent arriver par mail plutôt qu'être déposés à la main.
Ils sont envoyés par LightSpeed dans **deux messages distincts** : le premier
reçu patiente jusqu'à l'arrivée de son binôme, puis la synthèse est produite,
archivée et renvoyée automatiquement.

Deux réglages sont nécessaires sur le point de vente (Table de correspondance) :

- une **adresse mail de consolidation**, distincte de celle des exports
  comptables mais sur la même boîte — c'est elle qui aiguille le message vers
  la consolidation plutôt que vers la conversion ;
- le **site de consolidation**. Sans lui, la paire reçue reste en attente et un
  échec est signalé, plutôt que d'être calculée avec des périodes devinées.

Un rapport resté seul plus de 4 h déclenche une alerte interne. Les rapports en
attente sont visibles en haut de la page Consolidation. Voir
`docs/fetch_mail.md` pour le détail de l'appariement.

## Limites à ce stade

- **Les périodes de service sont définies dans le code**, pas dans la table de
  correspondance. Elles ne varient donc pas d'un client à l'autre. Le jour où
  ce sera nécessaire, leur place naturelle sera le référentiel du client.
- **La réception par mail a été éprouvée le 11/09/2026** sur un tenant client
  (cf. `docs/fetch_mail.md`), mais sur un seul : les cas d'appariement moins
  courants — envoi tardif du binôme, renvoi d'un rapport corrigé — n'ont pas
  encore été rencontrés en vrai.
