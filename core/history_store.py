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


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "fichier"


def record_conversion(
    client_id: str,
    res: ConversionResult,
    source_bytes: bytes,
    csv_bytes: bytes,
    horodatage: str,
) -> dict:
    """Enregistre une conversion (un fichier source = une entrée) et retourne
    l'entrée de journal écrite."""
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
    }

    index_path = client_history_index_path(client_id)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")

    return entree


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


def _parse_date_piece(date_piece: str | None) -> dt.date | None:
    if not date_piece:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(date_piece, fmt).date()
        except ValueError:
            continue
    return None


def detect_missing_days(entries: list[dict]) -> list[dict]:
    """Repère, pour chaque point de vente, les jours ouvrés sans conversion
    enregistrée entre la première et la dernière date connue. Purement
    informatif (n'importe quel point de vente peut légitimement être fermé
    un jour donné) : à vérifier au cas par cas, jamais bloquant."""
    par_pdv: dict[str, list[dt.date]] = {}
    for e in entries:
        d = _parse_date_piece(e.get("date_piece"))
        if d is None:
            continue
        par_pdv.setdefault(e["point_de_vente"], []).append(d)

    trous = []
    for pdv, dates in par_pdv.items():
        dates = sorted(set(dates))
        if len(dates) < 2:
            continue
        cursor = dates[0]
        connues = set(dates)
        while cursor < dates[-1]:
            cursor += dt.timedelta(days=1)
            if cursor not in connues:
                trous.append({"point_de_vente": pdv, "date_manquante": cursor.isoformat()})
    return trous
