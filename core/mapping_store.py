"""
Gestion des tables de correspondance (paramétrage métier), persistées en JSON
par client dans data/clients/<client_id>/mappings.json. Toute la logique de
"comptabilité" (comptes, codes analytiques, comptes de contrepartie...) est
éditable depuis l'app, rien n'est codé en dur dans le convertisseur.

Tables :
- comptes_de_vente     : référentiel pur des comptes de vente Pennylane
                         (code + libellé), sans lien avec LightSpeed - sert
                         uniquement à proposer une liste de choix fiable
                         (menu déroulant) plutôt que de la saisie libre.
- departements         : Département LightSpeed (LightSpeed n'a pas de
                         notion de "catégorie" indépendante : la référence
                         comptable EST le département) -> Compte de vente
                         (choisi dans comptes_de_vente) + taux de TVA nominal
                         (informatif : le taux réellement appliqué à chaque
                         ligne vient du fichier LightSpeed lui-même, pas
                         d'ici).
- codes_analytiques    : référentiel pur des codes analytiques Pennylane
                         (code + description), sans lien avec compte/pdv/
                         département - sert de liste de choix à la table
                         suivante, symétrique de comptes_de_vente.
- comptes_analytiques  : (Compte comptable, Point de vente, Département)
                         -> Famille + Code analytique (choisi dans
                         codes_analytiques). Les trois critères sont
                         nécessaires : LightSpeed ne fournissant aucune
                         notion d'analytique, c'est cette combinaison qui la
                         reconstitue entièrement. Hypothèse à confirmer avec
                         un cas réel : si un cas s'avère non réductible à
                         cette combinaison figée, une résolution dynamique
                         sera nécessaire à la place.
- comptes_paiement     : Mode de paiement LightSpeed -> Compte de contrepartie (banque/caisse)
- comptes_tva          : Taux de TVA -> Compte de TVA collectée
- points_de_vente      : liste des points de vente connus (code + libellé + adresse mail
                         de réception de l'export automatique, optionnelle)
- parametres           : réglages généraux (code journal, compte d'écart/report, etc.)
"""
from __future__ import annotations

import copy
import json
import os

from core.client_store import client_mappings_path

EMPTY_MAPPINGS = {
    "parametres": {
        "code_journal": "VT",
        "code_pays": "FR",
        "devise": "EUR",
        "famille_categorie_analytique": "POINT_DE_VENTE",
        "compte_ecart": "471000",
        "libelle_compte_ecart": "Compte d'attente - écart de report LightSpeed",
        "tolerance_equilibrage": 0.02,
    },
    "points_de_vente": [],
    "comptes_de_vente": [],
    "departements": [],
    "codes_analytiques": [],
    "comptes_analytiques": [],
    "comptes_paiement": [],
    "comptes_tva": [],
}

# Jeu d'exemple proposé à la création d'un client (repris de la logique du
# fichier "Patch Lightspeed vers Pennylane" transmis), purement indicatif :
# à valider et corriger avec le plan comptable réel du client avant tout
# usage en production.
DEFAULT_MAPPINGS = {
    "parametres": dict(EMPTY_MAPPINGS["parametres"]),
    "points_de_vente": [
        {"code": "REST", "libelle": "RESTAURANT"},
        {"code": "BARF", "libelle": "BAR FOOD"},
        {"code": "BARS", "libelle": "BAR SOMMELLERIE"},
        {"code": "SOM", "libelle": "SOMMELLERIE"},
        {"code": "ADD", "libelle": "VENTES ADDITIONNELLES"},
        {"code": "PARIS", "libelle": "PARIS 2.0"},
    ],
    "comptes_de_vente": [
        {"compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%"},
        {"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"},
    ],
    "departements": [
        {"categorie_lightspeed": "Cuisine - Entrée", "compte": "70110010", "taux_tva": "10%"},
        {"categorie_lightspeed": "Cuisine - Plat", "compte": "70110010", "taux_tva": "10%"},
        {"categorie_lightspeed": "Cuisine - Dessert", "compte": "70110010", "taux_tva": "10%"},
        {"categorie_lightspeed": "Softs", "compte": "70110010", "taux_tva": "10%"},
        {"categorie_lightspeed": "Alcool (200)", "compte": "70110200", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin et Champagne", "compte": "70110200", "taux_tva": "20%"},
    ],
    "codes_analytiques": [
        {"code_analytique": "REST", "description": "RESTAURANT"},
        {"code_analytique": "BARF", "description": "BAR FOOD"},
    ],
    "comptes_analytiques": [
        {"compte": "70110010", "point_de_vente": pdv, "categorie_lightspeed": dep, "famille": "POINT_DE_VENTE", "code_analytique": pdv}
        for pdv in ("REST", "BARF")
        for dep in ("Cuisine - Entrée", "Cuisine - Plat", "Cuisine - Dessert", "Softs")
    ] + [
        {"compte": "70110200", "point_de_vente": pdv, "categorie_lightspeed": dep, "famille": "POINT_DE_VENTE", "code_analytique": pdv}
        for pdv in ("REST", "BARF")
        for dep in ("Alcool (200)", "Vin et Champagne")
    ],
    "comptes_paiement": [
        {"mode_paiement": "Carte bleue", "compte": "511100", "libelle_compte": "Remises de cartes bancaires"},
        {"mode_paiement": "Espèces", "compte": "530000", "libelle_compte": "Caisse"},
        {"mode_paiement": "Chèque", "compte": "511200", "libelle_compte": "Chèques à encaisser"},
        {"mode_paiement": "Ticket restaurant", "compte": "511300", "libelle_compte": "Titres restaurant à encaisser"},
        {"mode_paiement": "Deliveroo", "compte": "411100", "libelle_compte": "Créances plateformes de livraison - Deliveroo"},
        {"mode_paiement": "UberEats", "compte": "411110", "libelle_compte": "Créances plateformes de livraison - UberEats"},
        {"mode_paiement": "Lightspeed Payments", "compte": "511400", "libelle_compte": "Lightspeed Payments à encaisser"},
        {"mode_paiement": "Tap to Pay sur iPhone", "compte": "511100", "libelle_compte": "Remises de cartes bancaires"},
    ],
    "comptes_tva": [
        {"taux": "5.5%", "compte": "445710", "libelle_compte": "TVA collectée 5.5%"},
        {"taux": "10%", "compte": "445711", "libelle_compte": "TVA collectée 10%"},
        {"taux": "20%", "compte": "445712", "libelle_compte": "TVA collectée 20%"},
    ],
}


def _ensure_file(client_id: str, seed: dict) -> str:
    path = client_mappings_path(client_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)
    return path


def load_mappings(client_id: str) -> dict:
    path = _ensure_file(client_id, EMPTY_MAPPINGS)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Complète les clés manquantes si le fichier a été créé par une version antérieure.
    merged = copy.deepcopy(EMPTY_MAPPINGS)
    for k, v in data.items():
        merged[k] = v
    return merged


def save_mappings(client_id: str, data: dict) -> None:
    path = client_mappings_path(client_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def seed_with_examples(client_id: str) -> dict:
    save_mappings(client_id, copy.deepcopy(DEFAULT_MAPPINGS))
    return copy.deepcopy(DEFAULT_MAPPINGS)


def reset_to_empty(client_id: str) -> dict:
    save_mappings(client_id, copy.deepcopy(EMPTY_MAPPINGS))
    return copy.deepcopy(EMPTY_MAPPINGS)


def ensure_points_de_vente(client_id: str, points: list[dict]) -> None:
    """Ajoute les points de vente listés s'ils sont absents, sans toucher au
    reste du référentiel ni aux points de vente déjà présents (jamais de
    suppression/écrasement) — pour re-garantir des points de vente par défaut
    à chaque démarrage sans perdre les personnalisations faites entre-temps."""
    mappings = load_mappings(client_id)
    existants = {p.get("code") for p in mappings.get("points_de_vente", [])}
    manquants = [p for p in points if p["code"] not in existants]
    if manquants:
        mappings.setdefault("points_de_vente", []).extend(manquants)
        save_mappings(client_id, mappings)


def ensure_comptes_de_vente(client_id: str, comptes: list[dict]) -> None:
    """Comme ensure_points_de_vente : ajoute les comptes listés s'ils sont
    absents (par code compte), sans jamais toucher à l'existant."""
    mappings = load_mappings(client_id)
    existants = {c.get("compte") for c in mappings.get("comptes_de_vente", [])}
    manquants = [c for c in comptes if c["compte"] not in existants]
    if manquants:
        mappings.setdefault("comptes_de_vente", []).extend(manquants)
        save_mappings(client_id, mappings)


def ensure_departements(client_id: str, departements: list[dict]) -> None:
    """Ajoute les départements listés s'ils sont absents (par nom de
    département), sans écraser un compte déjà renseigné manuellement."""
    mappings = load_mappings(client_id)
    existants = {_norm_key(d.get("categorie_lightspeed", "")) for d in mappings.get("departements", [])}
    manquants = [d for d in departements if _norm_key(d["categorie_lightspeed"]) not in existants]
    if manquants:
        mappings.setdefault("departements", []).extend(manquants)
        save_mappings(client_id, mappings)


def ensure_codes_analytiques(client_id: str, codes: list[dict]) -> None:
    """Ajoute les codes analytiques listés s'ils sont absents (par code),
    sans écraser une description déjà personnalisée."""
    mappings = load_mappings(client_id)
    existants = {c.get("code_analytique") for c in mappings.get("codes_analytiques", [])}
    manquants = [c for c in codes if c["code_analytique"] not in existants]
    if manquants:
        mappings.setdefault("codes_analytiques", []).extend(manquants)
        save_mappings(client_id, mappings)


def ensure_comptes_paiement(client_id: str, paiements: list[dict]) -> None:
    mappings = load_mappings(client_id)
    existants = {_norm_key(p.get("mode_paiement", "")) for p in mappings.get("comptes_paiement", [])}
    manquants = [p for p in paiements if _norm_key(p["mode_paiement"]) not in existants]
    if manquants:
        mappings.setdefault("comptes_paiement", []).extend(manquants)
        save_mappings(client_id, mappings)


def ensure_comptes_tva(client_id: str, taux_rows: list[dict]) -> None:
    mappings = load_mappings(client_id)
    existants = {t.get("taux") for t in mappings.get("comptes_tva", [])}
    manquants = [t for t in taux_rows if t["taux"] not in existants]
    if manquants:
        mappings.setdefault("comptes_tva", []).extend(manquants)
        save_mappings(client_id, mappings)


# --- Helpers de recherche (tolérants à la casse/espaces) -------------------

def _norm_key(s: str) -> str:
    return (s or "").strip().casefold()


def find_departement(mappings: dict, categorie_lightspeed: str) -> dict | None:
    """Retrouve le mapping du département LightSpeed (= la valeur de la
    colonne « Références comptables » du fichier source) vers son compte de
    vente. Le compte, lui, doit être choisi parmi ceux du référentiel
    « Comptes de vente » (cf. find_compte_reference)."""
    target = _norm_key(categorie_lightspeed)
    for row in mappings.get("departements", []):
        if _norm_key(row.get("categorie_lightspeed", "")) == target:
            return row
    return None


def find_compte_reference(mappings: dict, compte: str) -> dict | None:
    """Retrouve un compte dans le référentiel pur « Comptes de vente »
    (utilisé pour son libellé, et comme source de vérité des comptes valides
    proposés en liste déroulante dans les autres tables)."""
    for row in mappings.get("comptes_de_vente", []):
        if row.get("compte") == compte:
            return row
    return None


def find_code_analytique(mappings: dict, compte: str, point_de_vente: str, categorie_lightspeed: str) -> dict | None:
    """LightSpeed ne fournit aucune notion d'analytique : c'est la
    combinaison (compte, point de vente, département) qui la reconstitue -
    les trois critères sont nécessaires, un même compte pouvant porter un
    code analytique différent selon le point de vente ET selon le département
    (ex. un compte de boisson peut être « Sommellerie » ou « Bar » selon le
    département d'origine, même sur un seul et même point de vente)."""
    for row in mappings.get("comptes_analytiques", []):
        if (
            row.get("compte") == compte
            and _norm_key(row.get("point_de_vente", "")) == _norm_key(point_de_vente)
            and _norm_key(row.get("categorie_lightspeed", "")) == _norm_key(categorie_lightspeed)
        ):
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


def find_client_pdv_by_email(adresse_email: str) -> tuple[str, str] | None:
    """Retrouve (client_id, code_point_de_vente) à partir de l'adresse mail
    dédiée qui a reçu un export automatique. Utilisé par le service de fetch
    mail pour identifier client et point de vente sans jamais dépendre du nom
    de fichier : chaque point de vente a sa propre adresse (voir page
    « Table de correspondance »), ce qui rend l'identification fiable même si
    LightSpeed change un jour sa convention de nommage de fichier.

    Parcourt tous les clients à chaque appel plutôt que de maintenir un index
    séparé : le nombre de clients reste faible, et ça évite tout risque
    d'index désynchronisé après une modification manuelle du référentiel."""
    from core.client_store import list_clients  # import tardif : évite un cycle

    target = _norm_key(adresse_email)
    if not target:
        return None
    for client in list_clients():
        mappings = load_mappings(client["id"])
        for pdv in mappings.get("points_de_vente", []):
            if _norm_key(pdv.get("adresse_email", "")) == target:
                return client["id"], pdv["code"]
    return None


def set_pdv_adresse_email(client_id: str, code_pdv: str, adresse_email: str) -> None:
    """Renseigne l'adresse mail d'un point de vente existant, sans écraser une
    valeur déjà personnalisée (idempotent, comme ensure_points_de_vente)."""
    mappings = load_mappings(client_id)
    changed = False
    for pdv in mappings.get("points_de_vente", []):
        if pdv.get("code") == code_pdv and not pdv.get("adresse_email"):
            pdv["adresse_email"] = adresse_email
            changed = True
    if changed:
        save_mappings(client_id, mappings)
