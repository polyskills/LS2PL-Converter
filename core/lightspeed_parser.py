"""
Parseur du fichier d'export comptable LightSpeed (Restaurant / Retail).

Le fichier exporté par LightSpeed ("... export_accounting_...xls") est une
feuille unique organisée en deux blocs, sans en-têtes de colonnes stables
d'une ligne à l'autre (pas de tableau Excel structuré) :

Bloc 1 - Ventes par référence comptable (catégorie) :
    Références comptables | Quantité | Total | Rabais | Total TTC Moins
    les rabais | Montant taxé (10%) | TVA 10% | Montant taxé (20%) |
    TVA 20% | Total taxes | % | Total HT
    ... une ligne par catégorie, terminée par une ligne "Total EUR"

Bloc 2 - Encaissements :
    Modes de paiement | Montant (Moins retour)
    ... une ligne par mode de paiement, terminée par "Total des paiements"
    puis "Total des reports" (et son détail), puis les totaux généraux
    "Total EUR", "Total taxes EUR", "Total EUR (Moins les taxes)".

Ce module localise ces blocs par le libellé de leurs lignes plutôt que par
une position de cellule fixe, afin de rester robuste aux variations
mineures de mise en page d'un export à l'autre.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd


class LightspeedParseError(Exception):
    """Levée quand la structure attendue n'est pas retrouvée dans le fichier."""


@dataclass
class CategorieVente:
    libelle: str
    quantite: float | None
    total_ht: float
    taux_tva: str | None  # "10%" / "20%" / None si non taxé
    montant_tva: float
    total_ttc: float | None


@dataclass
class ModePaiement:
    libelle: str
    montant: float


@dataclass
class LigneReport:
    libelle: str
    montant: float


@dataclass
class LightspeedExport:
    source_filename: str
    categories: list = field(default_factory=list)          # list[CategorieVente]
    paiements: list = field(default_factory=list)            # list[ModePaiement]
    reports: list = field(default_factory=list)               # list[LigneReport]
    total_paiements: float = 0.0
    total_reports: float = 0.0
    total_eur_final: float = 0.0
    total_taxes_final: float = 0.0
    total_ht_final: float = 0.0
    date_detectee: str | None = None
    point_de_vente_suggere: str | None = None

    @property
    def ca_ht(self) -> float:
        return round(sum(c.total_ht for c in self.categories), 2)

    @property
    def ca_ttc(self) -> float:
        return round(sum((c.total_ttc or 0.0) for c in self.categories), 2)

    @property
    def tva_totale(self) -> float:
        return round(sum(c.montant_tva for c in self.categories), 2)

    def tva_par_taux(self) -> dict:
        out: dict = {}
        for c in self.categories:
            if c.taux_tva and c.montant_tva:
                out[c.taux_tva] = round(out.get(c.taux_tva, 0.0) + c.montant_tva, 2)
        return out


def _norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, str):
        v = v.replace("\xa0", "").replace(" ", "").replace(",", ".")
        if v == "" or v == "-":
            return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(f):
        return 0.0
    return f


def _guess_date_and_pdv(filename: str) -> tuple[str | None, str | None]:
    """Tente d'extraire une date (AAAAMMJJ) et un nom de point de vente du nom de fichier."""
    date_match = re.search(r"(20\d{2})(\d{2})(\d{2})", filename)
    date = None
    if date_match:
        y, m, d = date_match.groups()
        date = f"{d}/{m}/{y[-2:]}"

    stem = re.sub(r"\.\w+$", "", filename)
    stem = re.sub(r"^[0-9a-f]{6,}-", "", stem)  # préfixe d'upload éventuel
    stem = re.sub(r"(20\d{6}).*$", "", stem)
    stem = re.sub(r"(?i)^demo", "", stem)
    stem = re.sub(r"(?i)lightspeed|export|accounting|business", " ", stem)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    pdv = stem.title() if stem else None
    return date, pdv


def parse_lightspeed_export(file_bytes: bytes, filename: str) -> LightspeedExport:
    """Lit un export comptable LightSpeed (.xls ou .xlsx) et retourne sa structure."""
    engine = "xlrd" if filename.lower().endswith(".xls") else None
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None, engine=engine)
    except Exception as exc:  # pragma: no cover - message utilisateur
        raise LightspeedParseError(
            f"Impossible de lire « {filename} » comme un export LightSpeed (.xls/.xlsx) : {exc}"
        ) from exc

    col0 = df[0].map(_norm) if 0 in df.columns else pd.Series([], dtype=str)

    header_idx = col0[col0 == "Références comptables"].index
    if len(header_idx) == 0:
        raise LightspeedParseError(
            f"« {filename} » ne ressemble pas à un export comptable LightSpeed "
            "(ligne 'Références comptables' introuvable)."
        )
    header_idx = header_idx[0]

    total_idx_candidates = col0[(col0 == "Total EUR") & (col0.index > header_idx)].index
    if len(total_idx_candidates) == 0:
        raise LightspeedParseError(
            f"« {filename} » : fin du tableau des ventes ('Total EUR') introuvable."
        )
    bloc1_total_idx = total_idx_candidates[0]

    categories: list[CategorieVente] = []
    for i in range(header_idx + 1, bloc1_total_idx):
        libelle = _norm(df.iat[i, 0])
        if not libelle:
            continue
        total_ht = _num(df.iat[i, 11]) if df.shape[1] > 11 else 0.0
        base10 = _num(df.iat[i, 5]) if df.shape[1] > 5 else 0.0
        tva10 = _num(df.iat[i, 6]) if df.shape[1] > 6 else 0.0
        base20 = _num(df.iat[i, 7]) if df.shape[1] > 7 else 0.0
        tva20 = _num(df.iat[i, 8]) if df.shape[1] > 8 else 0.0
        ttc = _num(df.iat[i, 4]) if df.shape[1] > 4 else None
        quantite = _num(df.iat[i, 1]) if df.shape[1] > 1 else None

        if not total_ht and not tva10 and not tva20 and not base10 and not base20:
            continue  # ligne de catégorie sans aucune vente sur la période

        if tva20:
            taux, montant_tva = "20%", tva20
        elif tva10:
            taux, montant_tva = "10%", tva10
        else:
            taux, montant_tva = None, 0.0

        categories.append(
            CategorieVente(
                libelle=libelle,
                quantite=quantite,
                total_ht=round(total_ht, 2),
                taux_tva=taux,
                montant_tva=round(montant_tva, 2),
                total_ttc=round(ttc, 2) if ttc is not None else None,
            )
        )

    paiement_hdr = col0[(col0 == "Modes de paiement") & (col0.index > bloc1_total_idx)].index
    paiements: list[ModePaiement] = []
    total_paiements = 0.0
    reports: list[LigneReport] = []
    total_reports = 0.0
    total_eur_final = 0.0
    total_taxes_final = 0.0
    total_ht_final = 0.0

    if len(paiement_hdr):
        p_idx = paiement_hdr[0]
        j = p_idx + 1
        while j < len(df) and _norm(df.iat[j, 0]) != "Total des paiements":
            lbl = _norm(df.iat[j, 0])
            if lbl:
                paiements.append(ModePaiement(libelle=lbl, montant=round(_num(df.iat[j, 1]), 2)))
            j += 1
        if j < len(df):
            total_paiements = round(_num(df.iat[j, 1]), 2)
            j += 1
        if j < len(df) and _norm(df.iat[j, 0]) == "Total des reports":
            total_reports = round(_num(df.iat[j, 1]), 2)
            j += 1
            while j < len(df) and _norm(df.iat[j, 0]) not in (
                "Total EUR",
                "Total taxes EUR",
                "Total EUR (Moins les taxes)",
                "",
            ):
                lbl = _norm(df.iat[j, 0])
                reports.append(LigneReport(libelle=lbl, montant=round(_num(df.iat[j, 1]), 2)))
                j += 1
        while j < len(df):
            lbl = _norm(df.iat[j, 0])
            if lbl == "Total EUR":
                total_eur_final = round(_num(df.iat[j, 1]), 2)
            elif lbl == "Total taxes EUR":
                total_taxes_final = round(_num(df.iat[j, 1]), 2)
            elif lbl == "Total EUR (Moins les taxes)":
                total_ht_final = round(_num(df.iat[j, 1]), 2)
            j += 1

    date_detectee, pdv_suggere = _guess_date_and_pdv(filename)

    return LightspeedExport(
        source_filename=filename,
        categories=categories,
        paiements=paiements,
        reports=reports,
        total_paiements=total_paiements,
        total_reports=total_reports,
        total_eur_final=total_eur_final,
        total_taxes_final=total_taxes_final,
        total_ht_final=total_ht_final,
        date_detectee=date_detectee,
        point_de_vente_suggere=pdv_suggere,
    )
