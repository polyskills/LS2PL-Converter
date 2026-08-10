"""
La "moulinette" : transforme un LightspeedExport + les tables de mapping en
lignes d'écriture au format d'import avancé Pennylane, et calcule les
indicateurs de contrôle (CA source vs CA généré, équilibre débit/crédit).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.lightspeed_parser import LightspeedExport
from core.mapping_store import (
    find_code_analytique,
    find_compte_paiement,
    find_compte_tva,
    find_compte_vente,
)

# Ordre et libellés EXACTS des colonnes du modèle d'import avancé Pennylane.
PENNYLANE_COLUMNS = [
    "Date",
    "Code Journal",
    "Numéro de compte",
    "Libellé de compte",
    "Libellé de ligne",
    "Taux de TVA du compte",
    "Code pays du compte",
    "Libellé de pièce",
    "Numéro de pièce",
    "Débit et/ou Crédit",
    "Crédit",
    "Famille de catégories",
    "Catégorie",
    "Code analytique",
    "Identifiant de ligne",
    "Poids analytique",
    "Identifiant de lettrage",
    "Échéance",
]


@dataclass
class ConversionResult:
    source_filename: str
    point_de_vente: str
    lignes: list = field(default_factory=list)      # list[dict] clés = PENNYLANE_COLUMNS
    avertissements: list = field(default_factory=list)
    erreurs: list = field(default_factory=list)
    ca_ht_source: float = 0.0
    ca_ht_genere: float = 0.0
    tva_source: float = 0.0
    tva_genere: float = 0.0
    ttc_source: float = 0.0
    total_debit: float = 0.0
    total_credit: float = 0.0
    ecart_calcule: float = 0.0
    ecart_report_declare: float = 0.0

    @property
    def ca_ok(self) -> bool:
        return abs(round(self.ca_ht_source - self.ca_ht_genere, 2)) < 0.01

    @property
    def equilibre_ok(self) -> bool:
        return abs(round(self.total_debit - self.total_credit, 2)) < 0.01

    @property
    def sans_erreur(self) -> bool:
        return not self.erreurs


def convert(
    export: LightspeedExport,
    mappings: dict,
    point_de_vente: str,
    date_piece: str,
    numero_piece: str,
    libelle_piece: str | None = None,
    code_journal: str | None = None,
) -> ConversionResult:
    params = mappings.get("parametres", {})
    code_journal = code_journal or params.get("code_journal", "VT")
    code_pays = params.get("code_pays", "FR")
    famille_defaut = params.get("famille_categorie_analytique", "POINT_DE_VENTE")
    libelle_piece = libelle_piece or f"Ventes LightSpeed {export.source_filename}"

    res = ConversionResult(source_filename=export.source_filename, point_de_vente=point_de_vente)
    res.ca_ht_source = export.ca_ht
    res.tva_source = export.tva_totale
    res.ttc_source = export.ca_ttc
    res.ecart_report_declare = export.total_reports

    ligne_id = 1
    tva_dues: dict[str, float] = {}

    for cat in export.categories:
        compte_vente = find_compte_vente(mappings, cat.libelle)
        if compte_vente is None:
            res.avertissements.append(
                f"Catégorie « {cat.libelle} » non mappée dans « Comptes de vente » "
                f"→ ligne ignorée ({cat.total_ht:.2f} € HT non converti)."
            )
            continue

        if cat.taux_ambigu:
            res.avertissements.append(
                f"Catégorie « {cat.libelle} » : plusieurs taux de TVA détectés sur la même ligne "
                f"du fichier source — taux retenu {cat.taux_tva}, à vérifier manuellement."
            )

        code_analytique = find_code_analytique(mappings, compte_vente["compte"], point_de_vente)
        if code_analytique is None:
            # Le code analytique est la raison d'être de l'outil : une combinaison
            # (compte, point de vente) non paramétrée est traitée comme une erreur
            # bloquante, au même titre qu'une catégorie non mappée, et non comme un
            # simple avertissement.
            res.erreurs.append(
                f"Aucun code analytique paramétré pour le compte {compte_vente['compte']} "
                f"/ point de vente « {point_de_vente} » — complétez la table « Codes analytiques »."
            )
            famille_ligne, code_ligne = "", ""
        else:
            famille_ligne = code_analytique.get("famille") or famille_defaut
            code_ligne = code_analytique["code_analytique"]

        res.lignes.append(
            {
                "Date": date_piece,
                "Code Journal": code_journal,
                "Numéro de compte": compte_vente["compte"],
                "Libellé de compte": compte_vente.get("libelle_compte", ""),
                "Libellé de ligne": cat.libelle,
                "Taux de TVA du compte": cat.taux_tva or "",
                "Code pays du compte": code_pays,
                "Libellé de pièce": libelle_piece,
                "Numéro de pièce": numero_piece,
                "Débit et/ou Crédit": 0,
                "Crédit": round(cat.total_ht, 2),
                "Famille de catégories": famille_ligne,
                "Catégorie": point_de_vente,
                "Code analytique": code_ligne,
                "Identifiant de ligne": ligne_id,
                "Poids analytique": 1,
                "Identifiant de lettrage": "",
                "Échéance": "",
            }
        )
        res.ca_ht_genere = round(res.ca_ht_genere + cat.total_ht, 2)
        if cat.taux_tva and cat.montant_tva:
            tva_dues[cat.taux_tva] = round(tva_dues.get(cat.taux_tva, 0.0) + cat.montant_tva, 2)
        ligne_id += 1

    for taux, montant in tva_dues.items():
        compte_tva = find_compte_tva(mappings, taux)
        if compte_tva is None:
            res.erreurs.append(
                f"Aucun compte de TVA collectée paramétré pour le taux {taux} "
                f"→ écriture déséquilibrée de {montant:.2f} €."
            )
            continue
        res.lignes.append(
            {
                "Date": date_piece,
                "Code Journal": code_journal,
                "Numéro de compte": compte_tva["compte"],
                "Libellé de compte": compte_tva.get("libelle_compte", ""),
                "Libellé de ligne": f"TVA collectée {taux}",
                "Taux de TVA du compte": "",
                "Code pays du compte": code_pays,
                "Libellé de pièce": libelle_piece,
                "Numéro de pièce": numero_piece,
                "Débit et/ou Crédit": 0,
                "Crédit": montant,
                "Famille de catégories": "",
                "Catégorie": "",
                "Code analytique": "",
                "Identifiant de ligne": ligne_id,
                "Poids analytique": "",
                "Identifiant de lettrage": "",
                "Échéance": "",
            }
        )
        res.tva_genere = round(res.tva_genere + montant, 2)
        ligne_id += 1

    for p in export.paiements:
        compte_p = find_compte_paiement(mappings, p.libelle)
        if compte_p is None:
            res.erreurs.append(
                f"Mode de paiement « {p.libelle} » non mappé dans « Comptes de contrepartie » "
                f"→ encaissement de {p.montant:.2f} € non converti (écriture déséquilibrée)."
            )
            continue
        debit = round(p.montant, 2) if p.montant >= 0 else 0
        credit = round(-p.montant, 2) if p.montant < 0 else 0
        res.lignes.append(
            {
                "Date": date_piece,
                "Code Journal": code_journal,
                "Numéro de compte": compte_p["compte"],
                "Libellé de compte": compte_p.get("libelle_compte", ""),
                "Libellé de ligne": p.libelle,
                "Taux de TVA du compte": "",
                "Code pays du compte": code_pays,
                "Libellé de pièce": libelle_piece,
                "Numéro de pièce": numero_piece,
                "Débit et/ou Crédit": debit,
                "Crédit": credit,
                "Famille de catégories": "",
                "Catégorie": "",
                "Code analytique": "",
                "Identifiant de ligne": ligne_id,
                "Poids analytique": "",
                "Identifiant de lettrage": "",
                "Échéance": "",
            }
        )
        ligne_id += 1

    total_debit = sum(l["Débit et/ou Crédit"] for l in res.lignes)
    total_credit = sum(l["Crédit"] for l in res.lignes)
    ecart = round(total_debit - total_credit, 2)
    res.ecart_calcule = ecart

    tolerance = params.get("tolerance_equilibrage", 0.02)
    if abs(ecart) >= 0.01:
        compte_ecart = params.get("compte_ecart")
        libelle_ecart = params.get("libelle_compte_ecart", "Compte d'attente")
        res.lignes.append(
            {
                "Date": date_piece,
                "Code Journal": code_journal,
                "Numéro de compte": compte_ecart,
                "Libellé de compte": libelle_ecart,
                "Libellé de ligne": "Report / régularisation encaissements LightSpeed",
                "Taux de TVA du compte": "",
                "Code pays du compte": code_pays,
                "Libellé de pièce": libelle_piece,
                "Numéro de pièce": numero_piece,
                "Débit et/ou Crédit": round(-ecart, 2) if ecart < 0 else 0,
                "Crédit": round(ecart, 2) if ecart > 0 else 0,
                "Famille de catégories": "",
                "Catégorie": "",
                "Code analytique": "",
                "Identifiant de ligne": ligne_id,
                "Poids analytique": "",
                "Identifiant de lettrage": "",
                "Échéance": "",
            }
        )
        # Le report LightSpeed déclaré doit expliquer l'écart d'équilibrage :
        # total_reports négatif => une régularisation en crédit était attendue.
        attendu = round(-export.total_reports, 2)
        if abs(ecart - attendu) > tolerance:
            res.avertissements.append(
                f"⚠️ L'écart de régularisation calculé ({ecart:+.2f} €) ne correspond pas "
                f"exactement au « Total des reports » déclaré par LightSpeed "
                f"({export.total_reports:+.2f} €, attendu {attendu:+.2f} €). Vérifier les montants."
            )

    res.total_debit = round(sum(l["Débit et/ou Crédit"] for l in res.lignes), 2)
    res.total_credit = round(sum(l["Crédit"] for l in res.lignes), 2)

    if not res.ca_ok:
        res.erreurs.append(
            f"CA HT source ({res.ca_ht_source:.2f} €) ≠ CA HT généré ({res.ca_ht_genere:.2f} €) : "
            "des catégories n'ont pas été converties, complétez la table « Comptes de vente »."
        )
    if not res.equilibre_ok:
        res.erreurs.append(
            f"Écriture déséquilibrée : Débit {res.total_debit:.2f} € ≠ Crédit {res.total_credit:.2f} €."
        )

    return res
