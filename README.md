# Convertisseur LightSpeed → Pennylane

Application web (Streamlit) qui importe un export comptable **LightSpeed**
(`.xls`/`.xlsx`), le convertit en fichier d'**import avancé Pennylane**, et
contrôle que le chiffre d'affaires n'a pas été altéré pendant la conversion.

LightSpeed ne gère pas de code analytique. L'application le **reconstitue**
à partir de deux informations disponibles pour chaque écriture : le
**compte comptable** de vente (déduit de la catégorie LightSpeed) et le
**point de vente** (choisi à l'import, un fichier = un point de vente). Le
couple (compte, point de vente) est ensuite recherché dans une table pour
produire le code analytique attendu par Pennylane.

## Fonctionnement

1. **Import** (`app.py`) : dépose d'un ou plusieurs fichiers export
   LightSpeed. Chaque fichier est parsé (catégories de vente, TVA, modes de
   paiement, report de la veille), on lui associe un point de vente, une
   date de pièce et un numéro de pièce.
2. **Conversion** (`core/converter.py`) : chaque catégorie vendue devient une
   ligne de crédit sur le compte de vente mappé, avec son code analytique ;
   la TVA collectée est cumulée par taux ; chaque mode de paiement devient
   une ligne de débit sur son compte de contrepartie ; un écart éventuel
   (report d'encaissement de la veille) est neutralisé sur un compte
   d'attente dédié pour garantir une écriture équilibrée.
3. **Contrôle** : le CA HT du fichier source et celui du fichier généré sont
   comparés (doivent être strictement égaux), de même que le total débit et
   le total crédit. Toute catégorie ou mode de paiement non mappé est
   signalé comme avertissement ou erreur bloquante.
4. **Export** (`core/pennylane_export.py`) : génération du fichier `.xlsx`
   au format d'import avancé Pennylane (mêmes colonnes que le modèle
   officiel), téléchargeable depuis l'interface.

## Tables de correspondance (page « Table de correspondance »)

Toutes les règles métier sont éditables dans l'interface (pas de valeur en
dur dans le code) et persistées dans `data/mappings.json` :

- **Points de vente** : liste des sites/points de vente.
- **Comptes de vente** : catégorie LightSpeed → compte général Pennylane.
- **Codes analytiques** : (compte comptable, point de vente) → code
  analytique.
- **Contreparties de paiement** : mode de paiement LightSpeed → compte de
  banque/caisse.
- **TVA collectée** : taux de TVA → compte de TVA collectée.
- **Paramètres généraux** : code journal, code pays, compte d'écart
  utilisé pour équilibrer un éventuel report d'encaissement, etc.

Les valeurs par défaut fournies dans `core/mapping_store.py` reprennent la
logique du fichier de correspondance transmis (« Patch Lightspeed vers
Pennylane ») à titre d'exemple ; elles sont à ajuster au plan comptable réel
de chaque client depuis l'interface.

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

Les tests couvrent le parsing d'un export LightSpeed reconstitué (mêmes
valeurs que l'exemple fourni), la conservation du CA lors de la conversion,
l'équilibrage débit/crédit (y compris avec report de la veille), et la
détection des mappings manquants.
