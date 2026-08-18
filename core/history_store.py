"""
Historisation des conversions, par client, sans base de données : fichiers
horodatés sur disque + un journal append-only au format JSON Lines (une
ligne JSON par conversion), facile à relire, filtrer et auditer.

Conservé pour chaque conversion :
- le fichier source LightSpeed reçu (tel quel)
- le fichier CSV généré pour Pennylane
- les indicateurs de contrôle (CA source/généré, équilibre, écarts)
- la liste des avertissements et erreurs rencontrés
- un statut de synthèse : OK / AVERTISSEMENT / ERREUR
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid

from core.client_store import client_history_files_dir, client_history_index_path
from core.converter import ConversionResult

# Nombre maximum de conversions conservées par client (toutes indépendantes
# du point de vente) : au-delà, les plus anciennes sont purgées (journal +
# fichiers source/générés associés) à chaque nouvel enregistrement. Cet outil
# n'a pas vocation à être l'archive de référence sur la durée — les
# conversions plus anciennes restent consultables ailleurs (Pennylane,
# export comptable du client).
MAX_HISTORIQUE_CONVERSIONS = 45


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "fichier"


def record_conversion(
    client_id: str,
    res: ConversionResult,
    source_bytes: bytes,
    csv_bytes: bytes,
    horodatage: str,
    destinataires_email: list[str] | None = None,
) -> dict:
    """Enregistre une conversion (un fichier source = une entrée) et retourne
    l'entrée de journal écrite. `destinataires_email` : adresse(s) mail ayant
    reçu (ou censées recevoir, en cas d'échec) le résultat — uniquement pour
    les conversions issues du fetch automatique ; vide pour un import manuel
    (page Convertisseur), qui ne notifie personne par mail."""
    files_dir = client_history_files_dir(client_id)
    os.makedirs(files_dir, exist_ok=True)

    conv_id = uuid.uuid4().hex[:12]
    ts_compact = horodatage.replace(":", "").replace("-", "").replace(" ", "_")
    base_name = f"{ts_compact}__{_slug(res.point_de_vente)}__{_slug(res.source_filename)}"

    source_path = os.path.join(files_dir, f"{base_name}__source{os.path.splitext(res.source_filename)[1] or '.dat'}")
    with open(source_path, "wb") as f:
        f.write(source_bytes)

    csv_path = os.path.join(files_dir, f"{base_name}__genere.csv")
    with open(csv_path, "wb") as f:
        f.write(csv_bytes)

    if not res.sans_erreur:
        statut = "ERREUR"
    elif res.avertissements:
        statut = "AVERTISSEMENT"
    else:
        statut = "OK"

    entree = {
        "id": conv_id,
        "horodatage": horodatage,
        "point_de_vente": res.point_de_vente,
        "fichier_source_nom": res.source_filename,
        "fichier_source_chemin": source_path,
        "fichier_genere_chemin": csv_path,
        "statut": statut,
        "ca_ht_source": res.ca_ht_source,
        "ca_ht_genere": res.ca_ht_genere,
        "tva_source": res.tva_source,
        "ttc_source": res.ttc_source,
        "total_debit": res.total_debit,
        "total_credit": res.total_credit,
        "ecart_calcule": res.ecart_calcule,
        "ecart_report_declare": res.ecart_report_declare,
        "nb_avertissements": len(res.avertissements),
        "nb_erreurs": len(res.erreurs),
        "avertissements": res.avertissements,
        "erreurs": res.erreurs,
        "date_piece": res.lignes[0]["Date"] if res.lignes else None,
        "numero_piece": res.lignes[0]["Numéro de pièce"] if res.lignes else None,
        "destinataires_email": list(destinataires_email or []),
    }

    index_path = client_history_index_path(client_id)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")

    _purger_historique(client_id)

    return entree


def _purger_historique(client_id: str) -> None:
    """Ne conserve que les MAX_HISTORIQUE_CONVERSIONS conversions les plus
    récentes (toutes confondues, indépendamment du point de vente) : réécrit
    le journal sans les plus anciennes et supprime leurs fichiers source/
    générés associés, pour ne pas accumuler indéfiniment sur un disque non
    dimensionné pour ça."""
    entries = list_history(client_id)  # déjà trié par horodatage décroissant
    a_purger = entries[MAX_HISTORIQUE_CONVERSIONS:]
    if not a_purger:
        return

    for e in a_purger:
        for cle in ("fichier_source_chemin", "fichier_genere_chemin"):
            chemin = e.get(cle)
            if chemin and os.path.exists(chemin):
                os.remove(chemin)

    conservees = entries[:MAX_HISTORIQUE_CONVERSIONS]
    index_path = client_history_index_path(client_id)
    with open(index_path, "w", encoding="utf-8") as f:
        # Réécrit du plus ancien au plus récent (ordre naturel d'un journal
        # append-only), même si `entries` était trié à l'envers pour l'affichage.
        for e in reversed(conservees):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def list_history(client_id: str) -> list[dict]:
    index_path = client_history_index_path(client_id)
    if not os.path.exists(index_path):
        return []
    entries = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # ligne corrompue ignorée plutôt que de faire échouer tout l'historique
    entries.sort(key=lambda e: e.get("horodatage", ""), reverse=True)
    return entries


def jours_depuis_derniere_conversion_reussie(entries: list[dict]) -> int | None:
    """Nombre de jours écoulés depuis la dernière conversion au statut OK
    (succès sans avertissement ni erreur), toutes conversions confondues pour
    ce client. None si aucune conversion réussie n'est présente dans
    l'historique conservé (MAX_HISTORIQUE_CONVERSIONS) — ne veut pas
    forcément dire qu'il n'y en a jamais eu, seulement qu'elle est sortie de
    la fenêtre conservée ici ; les conversions plus anciennes restent
    consultables ailleurs (Pennylane, export comptable du client).

    `entries` est attendu trié par horodatage décroissant (cf. list_history)."""
    from core.timezone import now_local

    for e in entries:
        if e.get("statut") != "OK":
            continue
        try:
            derniere = dt.datetime.strptime(e["horodatage"], "%Y-%m-%d %H:%M:%S").date()
        except (KeyError, ValueError):
            continue
        return (now_local().date() - derniere).days
    return None


def echecs_apres_derniere_reussite(entries: list[dict]) -> list[dict]:
    """Tentatives en échec (statut ERREUR) survenues depuis la dernière
    conversion réussie (ou toutes les tentatives en échec présentes si
    aucune réussite dans l'historique conservé). Complète
    jours_depuis_derniere_conversion_reussie : une conversion réussie
    aujourd'hui ne veut pas dire que TOUT va bien si une tentative plus
    récente encore a échoué entre-temps (plusieurs cycles par jour) — sans ce
    signal séparé, l'alerte "dernière conversion réussie : aujourd'hui"
    donnerait à tort une impression de succès complet.

    `entries` est attendu trié par horodatage décroissant (cf. list_history)."""
    horodatage_derniere_reussite = next(
        (e.get("horodatage", "") for e in entries if e.get("statut") == "OK"), None
    )
    if horodatage_derniere_reussite is None:
        return [e for e in entries if e.get("statut") == "ERREUR"]
    return [
        e for e in entries
        if e.get("statut") == "ERREUR" and e.get("horodatage", "") > horodatage_derniere_reussite
    ]
