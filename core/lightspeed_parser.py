"""
Parseur du fichier d'export comptable LightSpeed (Restaurant / Retail).

Le fichier exporté par LightSpeed (".xls"/.xlsx/.csv "export_accounting...")
est un tableau unique organisé en deux blocs, sans structure de tableau
Excel figée (pas de nom de plage, pas d'en-têtes typés) :

Bloc 1 - Ventes par référence comptable (catégorie) :
    Références comptables | Quantité | Total | Rabais | (Total TTC net) |
    [Montant taxé | TVA X% ] x N | Total taxes | % | Total HT
    ... une ligne par catégorie, terminée par une ligne "Total EUR"

    IMPORTANT : le nombre de paires "Montant taxé / TVA X%" est VARIABLE
    d'un export à l'autre (LightSpeed n'inclut que les taux de TVA
    effectivement utilisés sur la période : parfois 10/20%, parfois
    10/20/5.5%, etc.). Le parseur détecte donc ces colonnes dynamiquement
    par leur intitulé ("TVA 10%", "TVA 5.5%"...) plutôt que par une
    position fixe — une position fixe casserait silencieusement dès qu'un
    taux supplémentaire ou différent apparaît, ce qui est inacceptable sur
    un fichier comptable.

Bloc 2 - Encaissements :
    Modes de paiement | Montant (Moins retour) [| Pourboire | Montant (Moins les pourboires)]
    ... une ligne par mode de paiement, terminée par "Total des paiements",
    puis, le cas échéant, "Total des reports" (+détail, optionnel — absent
    quand il n'y a pas d'écart de caisse reporté), puis les totaux généraux
    "Total EUR", "Total taxes EUR", "Total EUR (Moins les taxes)".

    IMPORTANT : sur les exports avec pourboires, LightSpeed ajoute deux
    colonnes ("Pourboire", "Montant (Moins les pourboires)") et déplace TOUS
    les totaux agrégés (Total des paiements, Total des reports, Total EUR...)
    dans la dernière colonne ("Montant (Moins les pourboires)", nette des
    pourboires) plutôt que "Montant (Moins retour)" (colonne 1, brute).

    Les pourboires SONT comptabilisés (cf. core.converter) : le montant brut
    encaissé ("Montant (Moins retour)", pourboire compris) reste au débit du
    compte de contrepartie de chaque mode de paiement, et le pourboire de
    chaque ligne (colonne "Pourboire") génère en parallèle une ligne de
    crédit dédiée sur un compte de pourboires propre à ce mode de paiement.
    Les totaux agrégés du bloc, eux, continuent à être lus dans la colonne
    nette des pourboires quand elle existe (cohérent avec le CA TTC des
    ventes, qui n'a jamais inclus les pourboires — sert au contrôle de
    cohérence ventes/encaissements affiché à l'écran, indépendant de
    l'écriture générée). Sans colonne "Pourboire" (export sans pourboire),
    on retombe sur la colonne brute comme avant, pour tout.

Formats supportés : .xls (ancien binaire Excel), .xlsx, .csv (séparateur ;
ou ,, détecté automatiquement).
"""
from __future__ import annotations

import csv
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
    taux_tva: str | None  # "10%" / "20%" / "5.5%" / None si non taxé
    montant_tva: float
    total_ttc: float | None
    taux_ambigu: bool = False  # True si plusieurs taux non nuls détectés sur la même ligne


@dataclass
class ModePaiement:
    libelle: str
    montant: float  # brut, pourboire compris - cf. note en tête de module
    pourboire: float = 0.0  # 0.0 si l'export ne comporte pas de colonne "Pourboire"


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
    taux_tva_detectes: list = field(default_factory=list)   # taux vus dans l'en-tête, pour info/debug

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

    @property
    def ecart_ventes_encaissements(self) -> float:
        """Total des encaissements moins total TTC des ventes déclaré par LightSpeed.
        Doit être égal à -total_reports (0 s'il n'y a pas de report)."""
        return round(self.total_paiements - self.total_eur_final, 2)

    @property
    def ventes_encaissements_coherents(self) -> bool:
        """Contrôle de premier niveau, indépendant du mapping comptable : l'écart entre
        ventes et encaissements déclaré par le fichier source doit être expliqué par un
        report connu. Un écart résiduel signale un fichier source incohérent/incomplet."""
        return abs(round(self.ecart_ventes_encaissements + self.total_reports, 2)) < 0.02


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


def _read_as_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise LightspeedParseError(f"« {filename} » : encodage du CSV non reconnu.")
        try:
            sample = "\n".join(text.splitlines()[:5])
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            sep = dialect.delimiter
        except csv.Error:
            sep = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
        return pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=str)

    engine = "xlrd" if lower.endswith(".xls") else None
    return pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, header=None, engine=engine)


# Colonnes dont l'intitulé exact identifie une position fixe dans le bloc "ventes".
_FIXED_HEADER_LABELS = {
    "references_comptables": "Références comptables",
    "quantite": "Quantité",
    "total": "Total",
    "rabais": "Rabais",
    "total_taxes": "Total taxes",
    "total_ht": "Total HT",
}

_TVA_HEADER_RE = re.compile(r"^TVA\s*([\d]+(?:[.,]\d+)?)\s*%$", re.IGNORECASE)


def _locate_ventes_columns(header_row: list[str], filename: str, exiger_colonne_tva: bool = True) -> dict:
    """Retrouve, par intitulé, la position de chaque colonne utile du bloc ventes,
    y compris un nombre variable de paires (Montant taxé / TVA X%).

    exiger_colonne_tva=False : ne lève pas d'erreur si aucune paire n'est trouvée
    (journée sans aucune ligne de vente à lire - cf. l'appelant, parse_lightspeed_export)."""

    def find_exact(label: str) -> int:
        for i, v in enumerate(header_row):
            if v == label:
                return i
        raise LightspeedParseError(
            f"« {filename} » : colonne « {label} » introuvable dans l'en-tête du tableau des ventes "
            f"({header_row}). Le format du fichier LightSpeed a peut-être changé."
        )

    idx_rabais = find_exact(_FIXED_HEADER_LABELS["rabais"])
    idx_total_taxes = find_exact(_FIXED_HEADER_LABELS["total_taxes"])
    idx_total_ht = find_exact(_FIXED_HEADER_LABELS["total_ht"])
    # Colonne "Total TTC net des rabais" : juste après "Rabais", intitulé parfois vide.
    idx_ttc = idx_rabais + 1

    # Paires de colonnes de TVA : toute colonne dont l'intitulé matche "TVA X%".
    # La colonne "Montant taxé" associée est celle qui la précède immédiatement.
    tva_pairs = []
    for i, v in enumerate(header_row):
        m = _TVA_HEADER_RE.match(v)
        if m:
            taux = f"{m.group(1).replace(',', '.')}%"
            base_idx = i - 1
            if base_idx < 0 or i >= idx_total_taxes:
                raise LightspeedParseError(
                    f"« {filename} » : colonne « {v} » à une position inattendue dans l'en-tête."
                )
            tva_pairs.append({"taux": taux, "base_idx": base_idx, "tva_idx": i})

    if not tva_pairs and exiger_colonne_tva:
        raise LightspeedParseError(
            f"« {filename} » : aucune colonne de taux de TVA (« TVA X% ») détectée dans l'en-tête "
            f"du tableau des ventes ({header_row})."
        )

    return {
        "idx_quantite": find_exact(_FIXED_HEADER_LABELS["quantite"]),
        "idx_ttc": idx_ttc,
        "idx_total_taxes": idx_total_taxes,
        "idx_total_ht": idx_total_ht,
        "tva_pairs": tva_pairs,
    }


_LABEL_MONTANT_NET_POURBOIRES = "Montant (Moins les pourboires)"
_LABEL_MONTANT_BRUT = "Montant (Moins retour)"
_LABEL_POURBOIRE = "Pourboire"


def _locate_montant_paiement_column(header_row: list[str]) -> int:
    """Colonne à utiliser pour les TOTAUX agrégés du bloc « Modes de paiement »
    (Total des paiements, Total EUR...) : la colonne nette des pourboires si
    elle existe (cohérent avec le CA TTC des ventes, qui n'inclut jamais les
    pourboires), sinon la colonne brute usuelle - jamais une position figée,
    pour ne pas casser silencieusement si LightSpeed réordonne encore ses
    colonnes."""
    for i, v in enumerate(header_row):
        if v == _LABEL_MONTANT_NET_POURBOIRES:
            return i
    for i, v in enumerate(header_row):
        if v == _LABEL_MONTANT_BRUT:
            return i
    return 1  # dernier recours : position historique, fichiers très simples sans en-tête détaillé


def _locate_montant_brut_et_pourboire(header_row: list[str], idx_montant_totaux: int) -> tuple[int, int | None]:
    """Colonnes à utiliser pour CHAQUE LIGNE de mode de paiement (à la
    différence des totaux ci-dessus) : le montant brut réellement encaissé
    ("Montant (Moins retour)", pourboire compris - c'est ce montant qui doit
    rester au débit du compte de contrepartie, cf. core.converter), et la
    colonne "Pourboire" elle-même si présente (sert à générer la ligne de
    crédit dédiée). Sans colonne brute distincte (export sans pourboire), il
    n'y a qu'une seule colonne de montant : celle des totaux fait aussi
    office de colonne brute."""
    idx_brut = None
    idx_pourboire = None
    for i, v in enumerate(header_row):
        if v == _LABEL_MONTANT_BRUT:
            idx_brut = i
        elif v == _LABEL_POURBOIRE:
            idx_pourboire = i
    if idx_brut is None:
        idx_brut = idx_montant_totaux
    return idx_brut, idx_pourboire


def parse_lightspeed_export(file_bytes: bytes, filename: str) -> LightspeedExport:
    """Lit un export comptable LightSpeed (.xls / .xlsx / .csv) et retourne sa structure."""
    try:
        df = _read_as_dataframe(file_bytes, filename)
    except LightspeedParseError:
        raise
    except Exception as exc:  # pragma: no cover - message utilisateur
        raise LightspeedParseError(
            f"Impossible de lire « {filename} » comme un export LightSpeed (.xls/.xlsx/.csv) : {exc}"
        ) from exc

    col0 = df[0].map(_norm) if 0 in df.columns else pd.Series([], dtype=str)

    header_idx_candidates = col0[col0 == _FIXED_HEADER_LABELS["references_comptables"]].index
    if len(header_idx_candidates) == 0:
        raise LightspeedParseError(
            f"« {filename} » ne ressemble pas à un export comptable LightSpeed "
            "(ligne 'Références comptables' introuvable)."
        )
    header_idx = header_idx_candidates[0]
    header_row = [_norm(v) for v in df.iloc[header_idx].tolist()]

    total_idx_candidates = col0[(col0 == "Total EUR") & (col0.index > header_idx)].index
    if len(total_idx_candidates) == 0:
        raise LightspeedParseError(
            f"« {filename} » : fin du tableau des ventes ('Total EUR') introuvable."
        )
    bloc1_total_idx = total_idx_candidates[0]

    # Journée sans aucune vente : LightSpeed ne génère alors AUCUNE paire de colonnes
    # "Montant taxé / TVA X%" dans l'en-tête (une par taux ayant eu de l'activité ce
    # jour-là - zéro activité, zéro colonne), directement suivi de la ligne "Total EUR"
    # sans aucune ligne de catégorie entre les deux. Cas normal (jour sans exploitation,
    # fermeture...), pas une anomalie de format : l'absence de colonne de taux de TVA
    # n'est exigée que s'il y a effectivement des lignes de vente à lire.
    sans_ligne_de_vente = bloc1_total_idx == header_idx + 1
    cols = _locate_ventes_columns(header_row, filename, exiger_colonne_tva=not sans_ligne_de_vente)

    categories: list[CategorieVente] = []
    for i in range(header_idx + 1, bloc1_total_idx):
        libelle = _norm(df.iat[i, 0])
        if not libelle:
            continue

        total_ht = _num(df.iat[i, cols["idx_total_ht"]])
        total_taxes = _num(df.iat[i, cols["idx_total_taxes"]])
        ttc = _num(df.iat[i, cols["idx_ttc"]]) if cols["idx_ttc"] < df.shape[1] else None
        quantite = _num(df.iat[i, cols["idx_quantite"]])

        taux_trouves = []
        for pair in cols["tva_pairs"]:
            montant_tva = _num(df.iat[i, pair["tva_idx"]])
            if montant_tva:
                taux_trouves.append((pair["taux"], montant_tva))

        if not total_ht and not total_taxes and not taux_trouves:
            continue  # ligne de catégorie sans aucune vente sur la période

        taux_ambigu = len(taux_trouves) > 1
        if taux_trouves:
            # Cas normal : un seul taux par ligne. En cas d'ambiguïté (plusieurs
            # taux non nuls sur la même ligne, jamais vu à ce jour mais possible),
            # on ne perd aucune donnée : Total HT / Total taxes déclarés par
            # LightSpeed font foi, et on retient le taux dominant pour l'affichage,
            # tout en signalant l'anomalie à l'appelant.
            taux_trouves.sort(key=lambda t: t[1], reverse=True)
            taux = taux_trouves[0][0]
            montant_tva = total_taxes if total_taxes else taux_trouves[0][1]
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
                taux_ambigu=taux_ambigu,
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
        # Machine à états, car deux variantes d'export ont été observées :
        #   (a) ... Total des paiements | Total des reports (+ détail) | Total EUR | Total taxes EUR | Total EUR (Moins les taxes)
        #   (b) ... Total EUR (directement, sans ligne "Total des paiements" ni report) | Total taxes EUR | Total EUR (Moins les taxes)
        # On pilote uniquement par intitulé de ligne, jamais par position, pour
        # rester robuste à ces variations et à d'éventuelles futures.
        p_idx = paiement_hdr[0]
        paiement_header_row = [_norm(v) for v in df.iloc[p_idx].tolist()]
        idx_montant = _locate_montant_paiement_column(paiement_header_row)
        idx_brut, idx_pourboire = _locate_montant_brut_et_pourboire(paiement_header_row, idx_montant)
        state = "PAIEMENTS"
        j = p_idx + 1
        while j < len(df):
            lbl = _norm(df.iat[j, 0])
            val = round(_num(df.iat[j, idx_montant]), 2)

            if state == "PAIEMENTS":
                if lbl == "Total des paiements":
                    total_paiements = val
                    state = "APRES_PAIEMENTS"
                elif lbl == "Total EUR":
                    # Pas de ligne "Total des paiements" distincte dans cet export :
                    # le total des encaissements et le total général sont la même valeur.
                    total_paiements = val
                    total_eur_final = val
                    state = "APRES_TOTAL_EUR"
                elif lbl:
                    montant_brut = round(_num(df.iat[j, idx_brut]), 2)
                    pourboire = round(_num(df.iat[j, idx_pourboire]), 2) if idx_pourboire is not None else 0.0
                    paiements.append(ModePaiement(libelle=lbl, montant=montant_brut, pourboire=pourboire))

            elif state == "APRES_PAIEMENTS":
                if lbl == "Total des reports":
                    total_reports = val
                    state = "DETAIL_REPORTS"
                elif lbl == "Total EUR":
                    total_eur_final = val
                    state = "APRES_TOTAL_EUR"
                elif lbl == "Total taxes EUR":
                    total_taxes_final = val
                elif lbl == "Total EUR (Moins les taxes)":
                    total_ht_final = val

            elif state == "DETAIL_REPORTS":
                if lbl == "Total EUR":
                    total_eur_final = val
                    state = "APRES_TOTAL_EUR"
                elif lbl:
                    reports.append(LigneReport(libelle=lbl, montant=val))

            elif state == "APRES_TOTAL_EUR":
                if lbl == "Total taxes EUR":
                    total_taxes_final = val
                elif lbl == "Total EUR (Moins les taxes)":
                    total_ht_final = val

            j += 1

        if state in ("PAIEMENTS",):
            raise LightspeedParseError(
                f"« {filename} » : fin du bloc « Modes de paiement » introuvable "
                "('Total des paiements' ou 'Total EUR' attendu) — impossible de vérifier "
                "que le total des ventes correspond au total des encaissements."
            )
    else:
        raise LightspeedParseError(
            f"« {filename} » : bloc « Modes de paiement » introuvable — impossible de vérifier "
            "que le total des ventes correspond au total des encaissements."
        )

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
        taux_tva_detectes=[p["taux"] for p in cols["tva_pairs"]],
    )
