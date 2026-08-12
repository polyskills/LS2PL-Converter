"""
Recrée automatiquement, à chaque démarrage, les seuls clients par défaut
(Paris/Valence). Le référentiel de chaque client (points de vente, comptes,
départements, codes analytiques, moyens de paiement, TVA...) n'est lui
JAMAIS peuplé automatiquement : il ne se remplit que par saisie manuelle
dans l'interface, ou par restauration d'une sauvegarde (page Réglages).

Sur Streamlit Community Cloud, le disque n'est pas persistant d'un
redéploiement/redémarrage à l'autre, et data/clients/ n'est volontairement
pas versionné dans git (données clients sensibles). Sans ce mécanisme, les
clients créés uniquement via l'interface disparaîtraient au premier reboot.

IMPORTANT : ensure_defaults() est appelé à CHAQUE rendu de page (via
core.ui_common.select_client()), pas seulement au démarrage du process -
Streamlit réexécute le script à chaque interaction. ensure_client() est
idempotent (ne recrée jamais un client déjà existant), donc rejouer cet
appel à chaque rendu ne pose pas de problème.
"""
from __future__ import annotations

from core.client_store import ensure_client

DEFAULT_CLIENTS = [
    {"id": "paris", "nom": "Paris"},
    {"id": "valence", "nom": "Valence"},
]


def ensure_defaults() -> None:
    for c in DEFAULT_CLIENTS:
        ensure_client(c["id"], c["nom"])
