"""
Réglages globaux de l'application, communs à tous les clients (à la
différence de core.mapping_store, propre à chacun) : persistés dans
data/app_config.json. Pour l'instant, uniquement le texte de pied de page
du menu latéral.
"""
from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CONFIG_PATH = os.path.join(BASE_DIR, "data", "app_config.json")

DEFAULT_APP_CONFIG = {
    "footer_sidebar": "© Polyskills - 2026",
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
