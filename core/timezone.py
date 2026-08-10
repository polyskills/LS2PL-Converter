"""
Fuseau horaire applicatif unique, pour que tous les horodatages affichés
(version déployée, date/heure de conversion, historique...) soient exprimés
dans le fuseau de l'activité (France) plutôt que dans celui, arbitraire, du
serveur d'hébergement (souvent UTC sur Streamlit Community Cloud) — gère
automatiquement le passage heure d'été/hiver.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Europe/Paris")


def now_local() -> dt.datetime:
    """Date/heure actuelle, dans le fuseau applicatif."""
    return dt.datetime.now(APP_TZ)


def to_local(value: dt.datetime | str) -> dt.datetime | None:
    """Convertit une date/heure (objet datetime ou chaîne ISO 8601) vers le
    fuseau applicatif. Une date naïve (sans fuseau, ex: horodatage déjà en
    heure locale mais non typé) est supposée déjà exprimée dans ce fuseau."""
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TZ)
    return value.astimezone(APP_TZ)
