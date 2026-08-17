"""
Registre des clients (mode multi-client / SaaS interne).

Chaque client dispose de son propre espace isolé sous data/clients/<id>/ :
- mappings.json      : ses tables de correspondance (voir mapping_store.py)
- history/index.jsonl : journal append-only de toutes ses conversions
- history/files/      : fichiers source et générés conservés en historique

Aucune authentification n'est mise en place à ce stade (usage interne,
équipe restreinte) : la sélection du client se fait via un simple menu en
haut de chaque page. À durcir avant tout accès externe.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTS_DIR = os.path.join(BASE_DIR, "data", "clients")
CLIENTS_INDEX = os.path.join(CLIENTS_DIR, "index.json")


def _slugify(nom: str) -> str:
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "client"


def _ensure_index() -> None:
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    if not os.path.exists(CLIENTS_INDEX):
        with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def list_clients() -> list[dict]:
    _ensure_index()
    with open(CLIENTS_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def get_client(client_id: str) -> dict | None:
    for c in list_clients():
        if c["id"] == client_id:
            return c
    return None


def create_client(nom: str) -> dict:
    _ensure_index()
    clients = list_clients()
    base_id = _slugify(nom)
    client_id = base_id
    n = 2
    existing_ids = {c["id"] for c in clients}
    while client_id in existing_ids:
        client_id = f"{base_id}-{n}"
        n += 1

    client = {"id": client_id, "nom": nom}
    clients.append(client)
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)

    os.makedirs(client_dir(client_id), exist_ok=True)
    os.makedirs(os.path.join(client_dir(client_id), "history", "files"), exist_ok=True)
    return client


def ensure_client(client_id: str, nom: str) -> dict:
    """Comme create_client, mais avec un identifiant fixe imposé plutôt que
    dérivé du nom, et idempotent : ne recrée rien si le client existe déjà.
    Utilisé pour les clients par défaut qui doivent survivre à un redémarrage
    Streamlit Cloud (disque non persistant, data/clients/ non versionné)."""
    _ensure_index()
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            return c

    client = {"id": client_id, "nom": nom}
    clients.append(client)
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)

    os.makedirs(client_dir(client_id), exist_ok=True)
    os.makedirs(os.path.join(client_dir(client_id), "history", "files"), exist_ok=True)
    return client


def rename_client(client_id: str, nouveau_nom: str) -> None:
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            c["nom"] = nouveau_nom
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)


def delete_client(client_id: str) -> None:
    """Supprime définitivement un client : sa fiche (index.json) ET tout son
    espace disque (référentiel, historique des conversions, fichiers
    archivés). Irréversible - à protéger d'une confirmation explicite côté
    interface avant tout appel."""
    clients = [c for c in list_clients() if c["id"] != client_id]
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)
    shutil.rmtree(client_dir(client_id), ignore_errors=True)


def set_email_config(client_id: str, tenant_id: str, mailbox: str) -> None:
    """Renseigne le tenant M365 et la boîte mail à interroger pour la
    réception automatique des exports LightSpeed de ce client. Les deux
    boîtes vivent dans le tenant du CLIENT (pas celui de Polyskills) : c'est
    ce tenant_id qui indique à quelle autorité Azure AD demander un jeton
    (authentification "application", cf. core.graph_client), après
    consentement admin donné par le client sur l'app multi-tenant Polyskills.
    Champs vides = fetch automatique désactivé pour ce client."""
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            c["email_tenant_id"] = tenant_id.strip()
            c["email_mailbox"] = mailbox.strip()
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)


def client_dir(client_id: str) -> str:
    return os.path.join(CLIENTS_DIR, client_id)


def client_mappings_path(client_id: str) -> str:
    return os.path.join(client_dir(client_id), "mappings.json")


def client_history_index_path(client_id: str) -> str:
    return os.path.join(client_dir(client_id), "history", "index.jsonl")


def client_history_files_dir(client_id: str) -> str:
    return os.path.join(client_dir(client_id), "history", "files")
