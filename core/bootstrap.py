"""
Données par défaut recréées automatiquement à chaque démarrage de l'app.

Sur Streamlit Community Cloud, le disque n'est pas persistant d'un
redéploiement/redémarrage à l'autre, et data/clients/ n'est volontairement
pas versionné dans git (données clients sensibles). Sans ce mécanisme, les
clients et points de vente créés uniquement via l'interface disparaîtraient
au premier reboot.

Ce module réinjecte, de façon idempotente (jamais de doublon, jamais
d'écrasement d'une personnalisation existante), les clients et points de
vente qui doivent survivre à un redémarrage. Toute autre donnée saisie dans
l'interface (comptes, codes analytiques...) reste, elle, soumise à la
persistance disque habituelle.
"""
from __future__ import annotations

from core.client_store import ensure_client
from core.mapping_store import ensure_points_de_vente, set_pdv_adresse_email

DEFAULT_CLIENTS = [
    {"id": "paris", "nom": "Paris"},
    {"id": "valence", "nom": "Valence"},
]

DEFAULT_POINTS_DE_VENTE = [
    {"code": "RESTAURANT", "libelle": "RESTAURANT"},
    {"code": "BAR", "libelle": "BAR"},
]

# Adresses mail dédiées à la réception automatique des exports LightSpeed,
# une par point de vente (cf. échange avec le client, août 2026). Ne
# concernent que le site Paris pour l'instant ; Valence n'a pas encore
# d'adresse dédiée, le champ y reste vide jusqu'à confirmation.
DEFAULT_ADRESSES_EMAIL = {
    "paris": {
        "RESTAURANT": "rapport_ls_paris_restaurant@annesophiepic-paris.com",
        "BAR": "rapport_ls_paris_bar@annesophiepic-paris.com",
    },
}


def ensure_defaults() -> None:
    for c in DEFAULT_CLIENTS:
        ensure_client(c["id"], c["nom"])
        ensure_points_de_vente(c["id"], DEFAULT_POINTS_DE_VENTE)
        for code_pdv, adresse in DEFAULT_ADRESSES_EMAIL.get(c["id"], {}).items():
            set_pdv_adresse_email(c["id"], code_pdv, adresse)
