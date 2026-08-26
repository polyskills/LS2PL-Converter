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

# Identifiants des clients explicitement supprimés via delete_client() — sert
# UNIQUEMENT à empêcher ensure_client() (core.bootstrap.ensure_defaults, rejoué
# à CHAQUE rendu de page) de recréer instantanément un client par défaut
# (Paris/Valence) juste supprimé : sans ce garde-fou, le client réapparaissait
# au rendu suivant, donnant l'impression que la suppression ne fonctionnait
# pas. N'affecte jamais une création explicite (create_client) : cf. l'ordre
# des vérifications dans ensure_client() plus bas.
CLIENTS_SUPPRIMES = os.path.join(CLIENTS_DIR, "_supprimes.json")


def _lire_supprimes() -> set[str]:
    if not os.path.exists(CLIENTS_SUPPRIMES):
        return set()
    with open(CLIENTS_SUPPRIMES, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _marquer_supprime(client_id: str) -> None:
    supprimes = _lire_supprimes()
    supprimes.add(client_id)
    os.makedirs(CLIENTS_DIR, exist_ok=True)
    with open(CLIENTS_SUPPRIMES, "w", encoding="utf-8") as f:
        json.dump(sorted(supprimes), f, ensure_ascii=False, indent=2)


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
    # Recréer explicitement un client anciennement supprimé (même identifiant,
    # ex. "Paris" re-saisi après suppression) doit annuler la marque laissée
    # par delete_client() - sinon une suppression FUTURE de ce nouveau client
    # laisserait un état incohérent (déjà marqué avant même la 1ère suppression).
    supprimes = _lire_supprimes()
    if client_id in supprimes:
        supprimes.discard(client_id)
        with open(CLIENTS_SUPPRIMES, "w", encoding="utf-8") as f:
            json.dump(sorted(supprimes), f, ensure_ascii=False, indent=2)
    return client


def ensure_client(client_id: str, nom: str) -> dict | None:
    """Comme create_client, mais avec un identifiant fixe imposé plutôt que
    dérivé du nom, et idempotent : ne recrée rien si le client existe déjà.
    Utilisé pour les clients par défaut qui doivent survivre à un redémarrage
    Streamlit Cloud (disque non persistant, data/clients/ non versionné).

    Ne recrée PAS non plus un client explicitement supprimé (delete_client) :
    une suppression volontaire doit être définitive, y compris pour un client
    par défaut - sans ce garde-fou (cf. CLIENTS_SUPPRIMES), il réapparaissait
    dès le rendu de page suivant. Vérifié seulement si le client n'existe pas
    déjà : une création explicite (create_client) réutilisant le même
    identifiant n'est jamais bloquée par un ancien passage ici."""
    _ensure_index()
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            return c
    if client_id in _lire_supprimes():
        return None

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
    interface avant tout appel.

    Marque aussi client_id comme explicitement supprimé (cf. CLIENTS_SUPPRIMES) :
    sans ça, un client par défaut (Paris/Valence, cf. core.bootstrap) était
    recréé instantanément au rendu de page suivant par ensure_defaults(),
    rendant sa suppression impossible en pratique."""
    clients = [c for c in list_clients() if c["id"] != client_id]
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)
    shutil.rmtree(client_dir(client_id), ignore_errors=True)
    _marquer_supprime(client_id)


def set_email_config(client_id: str, tenant_id: str, mailbox: str) -> None:
    """Renseigne le tenant M365 et la boîte mail à interroger pour la
    réception automatique des exports LightSpeed de ce client. Les deux
    vivent dans le tenant du CLIENT : c'est ce tenant_id qui indique à
    quelle autorité Azure AD demander un jeton (authentification
    "application", cf. core.graph_client), après consentement admin donné
    sur l'app Azure AD créée dans ce même tenant (cf.
    docs/configuration_m365_client.md). Champs vides = fetch automatique
    désactivé pour ce client."""
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            c["email_tenant_id"] = tenant_id.strip()
            c["email_mailbox"] = mailbox.strip()
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)


def set_azure_credentials(client_id: str, azure_client_id: str, azure_client_secret: str) -> None:
    """Renseigne l'ID d'application et le secret client de l'app Azure AD de
    ce client (créée dans son propre tenant, cf. set_email_config), utilisés
    pour l'authentification Graph du fetch automatique. Stockés en clair
    dans data/clients/index.json, comme le reste du référentiel — pas de
    chiffrement à ce stade (usage interne, équipe restreinte).

    Prioritaires sur les variables d'environnement globales
    LSPENNYLANE_AZURE_CLIENT_ID/_SECRET (legacy, un seul client par serveur) :
    cf. core.email_poller._identifiants_azure. Champs vides = repli sur ces
    variables d'environnement pour ce client."""
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            c["azure_client_id"] = azure_client_id.strip()
            c["azure_client_secret"] = azure_client_secret.strip()
    with open(CLIENTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)


DEFAULT_PREFIXE_MAIL = "LS2PL"


def get_prefixe_mail(client: dict) -> str:
    """Préfixe entre crochets utilisé dans le sujet des mails du fetch
    automatique (résultat de conversion, notifications d'échec côté client) -
    propre à chaque client (ex. "ASPP" pour Maison PIC Paris), pour se
    distinguer facilement dans une boîte mail au milieu d'autres échanges.
    Ne s'applique pas aux alertes internes (LSPENNYLANE_ALERTE_INTERNE),
    génériques et partagées entre tous les clients."""
    return (client.get("prefixe_mail") or "").strip() or DEFAULT_PREFIXE_MAIL


def set_prefixe_mail(client_id: str, prefixe: str) -> None:
    clients = list_clients()
    for c in clients:
        if c["id"] == client_id:
            c["prefixe_mail"] = prefixe.strip()
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
