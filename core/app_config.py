"""
Réglages globaux de l'application, communs à tous les clients (à la
différence de core.mapping_store, propre à chacun) : persistés dans
data/app_config.json. Le texte de pied de page du menu latéral, l'URL
publique de l'application (utilisée dans les mails de notification d'échec
du fetch automatique, pour renvoyer vers l'historique), et l'authentification
basique par code d'accès unique (page Réglages > Authentification).
"""
from __future__ import annotations

import hashlib
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CONFIG_PATH = os.path.join(BASE_DIR, "data", "app_config.json")

DEFAULT_APP_CONFIG = {
    "footer_sidebar": "© Polyskills - 2026",
    "url_app": "",
    "auth_active": False,
    "auth_mot_de_passe_hash": "",
}


def get_app_config() -> dict:
    if not os.path.exists(APP_CONFIG_PATH):
        return dict(DEFAULT_APP_CONFIG)
    with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_APP_CONFIG)
    merged.update(data)
    return merged


def save_app_config(config: dict) -> None:
    os.makedirs(os.path.dirname(APP_CONFIG_PATH), exist_ok=True)
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_footer_sidebar() -> str:
    return get_app_config().get("footer_sidebar") or DEFAULT_APP_CONFIG["footer_sidebar"]


def set_footer_sidebar(texte: str) -> None:
    config = get_app_config()
    config["footer_sidebar"] = texte
    save_app_config(config)


def get_url_app() -> str:
    """URL publique de l'application (ex. https://xxx.streamlit.app), sans
    slash final. Vide si non renseignée : les mails de notification d'échec
    du fetch automatique renvoient alors vers l'app en toutes lettres, sans
    lien cliquable."""
    return (get_app_config().get("url_app") or "").rstrip("/")


def set_url_app(url: str) -> None:
    config = get_app_config()
    config["url_app"] = url.strip().rstrip("/")
    save_app_config(config)


def _hash_mot_de_passe(mot_de_passe: str) -> str:
    """Hash simple (SHA-256, sans salage) : suffisant pour une authentification
    basique par code d'accès unique et partagé (usage interne, équipe
    restreinte, même modèle de confiance que le reste de l'app - cf. secrets
    Azure stockés en clair) - évite seulement qu'une lecture accidentelle de
    data/app_config.json expose le code en clair."""
    return hashlib.sha256(mot_de_passe.encode("utf-8")).hexdigest()


def is_auth_active() -> bool:
    """L'authentification protège l'accès à TOUTE l'application (demandée au
    chargement, avant même la sélection d'un client) - réglage global, un
    seul code partagé par toute l'équipe, pas de compte individuel."""
    return bool(get_app_config().get("auth_active", False))


def has_auth_password() -> bool:
    return bool(get_app_config().get("auth_mot_de_passe_hash"))


def set_auth_active(actif: bool) -> None:
    config = get_app_config()
    config["auth_active"] = bool(actif)
    save_app_config(config)


def set_auth_password(mot_de_passe: str) -> None:
    config = get_app_config()
    config["auth_mot_de_passe_hash"] = _hash_mot_de_passe(mot_de_passe)
    save_app_config(config)


def verifier_mot_de_passe(saisi: str) -> bool:
    hash_stocke = get_app_config().get("auth_mot_de_passe_hash") or ""
    if not hash_stocke:
        return False
    return _hash_mot_de_passe(saisi) == hash_stocke
