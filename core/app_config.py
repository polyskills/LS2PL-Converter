"""
Réglages globaux de l'application, communs à tous les clients (à la
différence de core.mapping_store, propre à chacun) : persistés dans
data/app_config.json. Le texte de pied de page du menu latéral, et l'URL
publique de l'application (utilisée dans les mails de notification d'échec
du fetch automatique, pour renvoyer vers l'historique).
"""
from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CONFIG_PATH = os.path.join(BASE_DIR, "data", "app_config.json")

DEFAULT_APP_CONFIG = {
    "footer_sidebar": "© Polyskills - 2026",
    "url_app": "",
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
