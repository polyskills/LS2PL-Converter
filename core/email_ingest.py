"""
Identification de la source d'un export LightSpeed reçu par mail.

Ce module ne fait *pas* le fetch de la boîte mail (ça dépend encore de savoir
quel tenant M365 héberge les adresses dédiées — cf. échange client) : il
fournit uniquement la logique déterministe, indépendante du transport, que le
futur service de fetch appellera pour chaque pièce jointe reçue :

1. identifier client + point de vente à partir de l'adresse destinataire du
   mail (cf. core.mapping_store.find_client_pdv_by_email) — jamais à partir
   du nom de fichier, qui n'est pas une source fiable pour ça ;
2. extraire la période couverte par l'export depuis le nom de fichier, pour
   pré-remplir la date de pièce.

Convention de nommage observée sur les exports réels — le préfixe varie
(nom de client/pdv, "business_export_accounting", ou tout autre libellé),
mais se termine TOUJOURS par les deux dates de la période au format
AAAAMMJJ_AAAAMMJJ, juste avant l'extension :
    annesophiepicparis_ladamedepicbar_business_export_accounting_20260810_20260811.xls
    test-mail-automatique_20260826_20260827.xls
    -> période couverte respectivement du 10/08/2026 au 11/08/2026, et du
       26/08/2026 au 27/08/2026.
Le préfixe client/pdv du nom de fichier n'est volontairement pas exploité
pour l'identification (c'est l'adresse mail qui fait foi) : il ne sert que de
garde-fou optionnel, en warning, si jamais un fichier atterrit sur la mauvaise
adresse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.mapping_store import find_client_pdv_by_email

# Ancré en fin de nom de fichier (juste avant une éventuelle extension) plutôt
# que sur le libellé fixe "business_export_accounting_" : ce dernier n'est
# qu'une convention parmi d'autres observées, alors que les deux dates en fin
# de nom, elles, sont systématiques quel que soit le préfixe utilisé.
_PERIODE_RE = re.compile(r"(\d{8})_(\d{8})(?:\.\w+)?$", re.IGNORECASE)


class EmailIngestError(Exception):
    """Levée quand l'adresse destinataire ne correspond à aucun point de vente connu."""


@dataclass
class SourceIdentifiee:
    client_id: str
    code_pdv: str
    date_debut: str | None  # "dd/mm/aa"
    date_fin: str | None    # "dd/mm/aa"
    avertissement: str | None = None


def _formate_date(brut: str) -> str:
    y, m, d = brut[:4], brut[4:6], brut[6:8]
    return f"{d}/{m}/{y[-2:]}"


def date_aaaammjj(date_piece: str) -> str:
    """Convertit une date de pièce "dd/mm/aa" (format utilisé pour la pièce
    comptable, cf. numero_piece) en "AAAAMMJJ" pour un nom de fichier — même
    convention que les exports LightSpeed source (l'inverse de _formate_date
    ci-dessus). Suppose le XXIe siècle (2000+aa), sans ambiguïté pour un usage
    courant de l'application. Partagé entre core.email_poller (résultat du
    fetch automatique) et pages.converter (téléchargement manuel)."""
    d, m, y = date_piece.split("/")
    return f"20{y}{m}{d}"


def extraire_periode(filename: str) -> tuple[str | None, str | None]:
    """Extrait (date_debut, date_fin) du nom de fichier, au format dd/mm/aa.
    Retourne (None, None) si le nom de fichier ne suit pas la convention
    attendue (`..._business_export_accounting_AAAAMMJJ_AAAAMMJJ.ext`)."""
    m = _PERIODE_RE.search(filename)
    if not m:
        return None, None
    return _formate_date(m.group(1)), _formate_date(m.group(2))


def identifier_source(adresse_destinataire: str, filename: str) -> SourceIdentifiee:
    """Point d'entrée du futur service de fetch mail, pour une pièce jointe
    donnée. Lève EmailIngestError si l'adresse destinataire n'est rattachée
    à aucun point de vente du référentiel (mail à ne pas traiter
    automatiquement — alerte interne plutôt que perte silencieuse)."""
    trouve = find_client_pdv_by_email(adresse_destinataire)
    if trouve is None:
        raise EmailIngestError(
            f"Adresse « {adresse_destinataire} » non rattachée à un point de vente : "
            "vérifier la table de correspondance avant de pouvoir traiter ce mail automatiquement."
        )
    client_id, code_pdv = trouve

    date_debut, date_fin = extraire_periode(filename)

    avertissement = None
    if date_debut is None:
        avertissement = (
            f"« {filename} » ne suit pas la convention de nommage attendue "
            "(période introuvable) — date de pièce à vérifier manuellement."
        )

    return SourceIdentifiee(
        client_id=client_id,
        code_pdv=code_pdv,
        date_debut=date_debut,
        date_fin=date_fin,
        avertissement=avertissement,
    )
