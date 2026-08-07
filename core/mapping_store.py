"""
Gestion des tables de correspondance (paramétrage métier), persistées en JSON
dans data/mappings.json. Toute la logique de "comptabilité" (comptes,
codes analytiques, comptes de contrepartie...) est éditable depuis l'app,
rien n'est codé en dur dans le convertisseur.

Quatre tables :
- comptes_ventes       : Catégorie LightSpeed -> Compte de vente Pennylane (+ taux TVA nominal)
- comptes_analytiques  : (Compte comptable, Point de vente) -> Code analytique
- comptes_paiement     : Mode de paiement LightSpeed -> Compte de contrepartie (banque/caisse)
- comptes_tva          : Taux de TVA -> Compte de TVA collectée
- points_de_vente      : liste des points de vente connus (code + libellé)
- parametres           : réglages généraux (code journal, compte d'écart/report, etc.)
"""
from __future__ import annotations

import copy
import json
import os

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mappings.json")

DEFAULT_MAPPINGS = {
    "parametres": {
        "code_journal": "VT",
        "code_pays": "FR",
        "devise": "EUR",
        "famille_categorie_analytique": "POINT_DE_VENTE",
        "compte_ecart": "471000",
        "libelle_compte_ecart": "Compte d'attente - écart de report LightSpeed",
        "tolerance_equilibrage": 0.02,
    },
    "points_de_vente": [
        {"code": "REST", "libelle": "RESTAURANT"},
        {"code": "BARF", "libelle": "BAR FOOD"},
        {"code": "BARS", "libelle": "BAR SOMMELLERIE"},
        {"code": "SOM", "libelle": "SOMMELLERIE"},
        {"code": "ADD", "libelle": "VENTES ADDITIONNELLES"},
        {"code": "PARIS", "libelle": "PARIS 2.0"},
    ],
    # Exemple de départ repris du fichier "Patch Lightspeed vers Pennylane" fourni :
    # catégorie/référence comptable LightSpeed -> compte général Pennylane.
    "comptes_ventes": [
        {"categorie_lightspeed": "Cuisine - Entrée", "compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%", "taux_tva": "10%"},
        {"categorie_lightspeed": "Cuisine - Plat", "compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%", "taux_tva": "10%"},
        {"categorie_lightspeed": "Cuisine - Dessert", "compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%", "taux_tva": "10%"},
        {"categorie_lightspeed": "Softs", "compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%", "taux_tva": "10%"},
        {"categorie_lightspeed": "Alcool (200)", "compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin et Champagne", "compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%", "taux_tva": "20%"},
    ],
    "comptes_analytiques": [
        {"compte": "70110010", "point_de_vente": "REST", "code_analytique": "REST"},
        {"compte": "70110200", "point_de_vente": "REST", "code_analytique": "REST"},
        {"compte": "70110010", "point_de_vente": "BARF", "code_analytique": "BARF"},
        {"compte": "70110200", "point_de_vente": "BARF", "code_analytique": "BARF"},
    ],
    "comptes_paiement": [
        {"mode_paiement": "Carte bleue", "compte": "511100", "libelle_compte": "Remises de cartes bancaires"},
        {"mode_paiement": "Espèces", "compte": "530000", "libelle_compte": "Caisse"},
        {"mode_paiement": "Chèque", "compte": "511200", "libelle_compte": "Chèques à encaisser"},
        {"mode_paiement": "Ticket restaurant", "compte": "511300", "libelle_compte": "Titres restaurant à encaisser"},
    ],
    "comptes_tva": [
        {"taux": "10%", "compte": "445711", "libelle_compte": "TVA collectée 10%"},
        {"taux": "20%", "compte": "445712", "libelle_compte": "TVA collectée 20%"},
    ],
}


def _ensure_file() -> None:
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    if not os.path.exists(DATA_PATH):
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MAPPINGS, f, ensure_ascii=False, indent=2)


def load_mappings() -> dict:
    _ensure_file()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Complète les clés manquantes si le fichier a été créé par une version antérieure.
    merged = copy.deepcopy(DEFAULT_MAPPINGS)
    for k, v in data.items():
        merged[k] = v
    return merged


def save_mappings(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reset_to_defaults() -> dict:
    save_mappings(DEFAULT_MAPPINGS)
    return copy.deepcopy(DEFAULT_MAPPINGS)


# --- Helpers de recherche (tolérants à la casse/espaces) -------------------

def _norm_key(s: str) -> str:
    return (s or "").strip().casefold()


def find_compte_vente(mappings: dict, categorie_lightspeed: str) -> dict | None:
    target = _norm_key(categorie_lightspeed)
    for row in mappings.get("comptes_ventes", []):
        if _norm_key(row.get("categorie_lightspeed", "")) == target:
            return row
    return None


def find_code_analytique(mappings: dict, compte: str, point_de_vente: str) -> dict | None:
    for row in mappings.get("comptes_analytiques", []):
        if row.get("compte") == compte and _norm_key(row.get("point_de_vente", "")) == _norm_key(point_de_vente):
            return row
    return None


def find_compte_paiement(mappings: dict, mode_paiement: str) -> dict | None:
    target = _norm_key(mode_paiement)
    for row in mappings.get("comptes_paiement", []):
        if _norm_key(row.get("mode_paiement", "")) == target:
            return row
    return None


def find_compte_tva(mappings: dict, taux: str) -> dict | None:
    for row in mappings.get("comptes_tva", []):
        if row.get("taux") == taux:
            return row
    return None
