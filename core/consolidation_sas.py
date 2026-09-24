"""
Sas d'attente d'appariement des rapports de consolidation reçus par mail.

Une consolidation a besoin de DEUX rapports Lightspeed — Tickets et
Transactions — d'une même période, et ils arrivent dans deux messages
distincts. Le poller ne peut donc pas traiter un message dès sa réception
comme il le fait pour un export comptable : le premier arrivé doit patienter.

Ce module est ce lieu d'attente. Le rapport reçu est écrit sur disque sous sa
clé d'appariement, le message est marqué lu comme d'habitude, et le traitement
se déclenche quand le binôme arrive. On garde ainsi l'invariant du poller —
un message vu est un message traité — sans re-télécharger indéfiniment des
pièces jointes en attendant une paire (ce qu'imposerait de laisser les
messages non lus), et l'attente survit à un redémarrage du service.

Clé d'appariement : (point de vente, date de début, date de fin). Elle vient
de l'adresse destinataire pour le point de vente et du nom de fichier pour la
période — jamais de l'heure d'arrivée des messages, qui ne prouve rien. Deux
journées différentes ont donc deux clés, et peuvent attendre en parallèle sans
se mélanger.

Arborescence, sous data/clients/<id>/consolidations/en_attente/<cle>/ :
    etat.json               ce qui est déjà arrivé, et depuis quand
    tickets.<ext>           contenu brut du rapport, tel que reçu
    transactions.<ext>

etat.json ne retient que le NOM des fichiers, jamais leur chemin complet : le
dossier se reconstruit à partir de (client, clé), et une sauvegarde restaurée
sur une autre machine reste donc exploitable.

Une paire complète qui reste dans le sas est une paire dont la consolidation a
ÉCHOUÉ : les fichiers y sont conservés plutôt que perdus, et la paire est
retentée à chaque cycle (cf. core.email_poller.reprendre_paires_en_echec) —
la cause étant presque toujours à corriger dans le référentiel, pas dans le
sas. Le motif du dernier échec est mémorisé pour ne notifier qu'une fois par
cause (cf. marquer_echec).

Deux garde-fous temporels :
- DELAI_ALERTE_HEURES : au-delà, un rapport resté seul devient un incident
  signalé (un export cassé côté Lightspeed ne doit pas passer inaperçu) ;
- RETENTION_JOURS : au-delà, il est abandonné, pour que le sas ne grossisse
  pas indéfiniment. Entre les deux, un binôme tardif complète encore la paire.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil

from core.client_store import client_consolidation_sas_dir

# Un rapport seul au-delà de ce délai est signalé comme incident : c'est le
# symptôme d'un export qui ne part plus côté Lightspeed, et le silence serait
# le pire des comportements.
DELAI_ALERTE_HEURES = 4

# Au-delà, le rapport orphelin est abandonné : passé une semaine, la période
# concernée aura été traitée autrement (dépôt manuel), et le garder ne ferait
# qu'encombrer.
RETENTION_JOURS = 7

TYPE_TICKETS = "tickets"
TYPE_TRANSACTIONS = "transactions"
TYPES_RAPPORTS = (TYPE_TICKETS, TYPE_TRANSACTIONS)

_FORMAT_HORODATAGE = "%Y-%m-%d %H:%M:%S"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(s)) or "x"


def cle_appariement(code_pdv: str, date_debut: str | None, date_fin: str | None) -> str:
    """Identifiant du couple attendu. Les dates arrivent au format "dd/mm/aa"
    (cf. core.email_ingest) ; on les réduit à des chiffres pour en faire un nom
    de dossier sûr."""
    return f"{_slug(code_pdv)}__{_slug(date_debut or 'sansdate')}__{_slug(date_fin or 'sansdate')}"


def _dossier(client_id: str, cle: str) -> str:
    return os.path.join(client_consolidation_sas_dir(client_id), cle)


def chemin_rapport(client_id: str, cle: str, infos: dict) -> str | None:
    """Chemin absolu du fichier d'un rapport en attente.

    Le sas n'enregistre que le NOM du fichier : son dossier est entièrement
    déterminé par (client, clé d'appariement), donc reconstructible. Y stocker
    un chemin absolu le rendrait faux dès qu'une sauvegarde est restaurée
    ailleurs — la paire resterait complète mais illisible, et la consolidation
    ne se déclencherait jamais (même raison qu'en historique, cf.
    core.history_store.chemin_fichier).

    Un état écrit avant ce changement porte un chemin absolu : on tente
    d'abord le chemin reconstruit, valable dans tous les cas, puis l'ancien
    s'il existe encore. None si le fichier reste introuvable."""
    stocke = infos.get("chemin") or ""
    if not stocke:
        return None
    candidat = os.path.join(_dossier(client_id, cle), os.path.basename(stocke))
    if os.path.exists(candidat):
        return candidat
    if os.path.isabs(stocke) and os.path.exists(stocke):
        return stocke
    return None


def _chemin_etat(client_id: str, cle: str) -> str:
    return os.path.join(_dossier(client_id, cle), "etat.json")


def _lire_etat(client_id: str, cle: str) -> dict | None:
    chemin = _chemin_etat(client_id, cle)
    if not os.path.exists(chemin):
        return None
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _ecrire_etat(client_id: str, cle: str, etat: dict) -> None:
    os.makedirs(_dossier(client_id, cle), exist_ok=True)
    with open(_chemin_etat(client_id, cle), "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)


def deposer(
    client_id: str,
    code_pdv: str,
    date_debut: str | None,
    date_fin: str | None,
    type_rapport: str,
    nom_fichier: str,
    contenu: bytes,
    horodatage: str,
    adresses_notification: list[str] | None = None,
) -> dict:
    """Range un rapport dans le sas et renvoie l'état de la clé concernée.

    Un rapport déjà présent est REMPLACÉ : un renvoi manuel du même export
    doit écraser le précédent, pas créer un doublon ni être ignoré — c'est
    presque toujours une correction."""
    if type_rapport not in TYPES_RAPPORTS:
        raise ValueError(f"Type de rapport inconnu : {type_rapport}")

    cle = cle_appariement(code_pdv, date_debut, date_fin)
    etat = _lire_etat(client_id, cle) or {
        "cle": cle,
        "client_id": client_id,
        "code_pdv": code_pdv,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "rapports": {},
        "alerte_envoyee": False,
    }

    extension = os.path.splitext(nom_fichier)[1] or ".dat"
    chemin = os.path.join(_dossier(client_id, cle), f"{type_rapport}{extension}")
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "wb") as f:
        f.write(contenu)

    ancien = etat["rapports"].get(type_rapport)
    if ancien:
        ancien_chemin = chemin_rapport(client_id, cle, ancien)
        if ancien_chemin and os.path.abspath(ancien_chemin) != os.path.abspath(chemin):
            os.remove(ancien_chemin)  # extension différente : ne pas laisser l'ancien fichier derrière

    etat["rapports"][type_rapport] = {
        "nom_fichier": nom_fichier,
        # Nom seul, jamais le chemin complet : cf. chemin_rapport.
        "chemin": os.path.basename(chemin),
        "horodatage": horodatage,
        "adresses_notification": list(adresses_notification or []),
        "remplace": bool(ancien),
    }
    _ecrire_etat(client_id, cle, etat)
    return etat


def est_complet(etat: dict) -> bool:
    return all(t in (etat.get("rapports") or {}) for t in TYPES_RAPPORTS)


def charger_paire(client_id: str, cle: str) -> tuple[list, list] | None:
    """(tickets, transactions) au format attendu par
    core.lightspeed_synthese.construire_synthese — des couples (nom, octets).
    None si la paire n'est pas complète ou si un fichier a disparu du disque."""
    etat = _lire_etat(client_id, cle)
    if etat is None or not est_complet(etat):
        return None
    contenus = {}
    for type_rapport in TYPES_RAPPORTS:
        infos = etat["rapports"][type_rapport]
        chemin = chemin_rapport(client_id, cle, infos)
        if chemin is None:
            return None
        with open(chemin, "rb") as f:
            contenus[type_rapport] = [(infos["nom_fichier"], f.read())]
    return contenus[TYPE_TICKETS], contenus[TYPE_TRANSACTIONS]


def retirer(client_id: str, cle: str) -> None:
    """Vide la clé, une fois la paire consolidée (ou abandonnée)."""
    shutil.rmtree(_dossier(client_id, cle), ignore_errors=True)


def lister(client_id: str) -> list[dict]:
    """États en attente pour ce client, du plus ancien dépôt au plus récent —
    de quoi afficher « en attente du rapport Transactions du 07/09 »."""
    racine = client_consolidation_sas_dir(client_id)
    if not os.path.isdir(racine):
        return []
    etats = []
    for cle in sorted(os.listdir(racine)):
        etat = _lire_etat(client_id, cle)
        if etat is not None:
            etats.append(etat)
    etats.sort(key=depose_le)
    return etats


def depose_le(etat: dict) -> str:
    """Horodatage du premier rapport arrivé pour cette clé : c'est de lui que
    court le délai d'alerte, pas du plus récent."""
    horodatages = [r.get("horodatage", "") for r in (etat.get("rapports") or {}).values()]
    return min([h for h in horodatages if h], default="")


def rapport_manquant(etat: dict) -> str | None:
    manquants = [t for t in TYPES_RAPPORTS if t not in (etat.get("rapports") or {})]
    return manquants[0] if manquants else None


def _age_heures(etat: dict, maintenant: dt.datetime) -> float | None:
    depose = depose_le(etat)
    if not depose:
        return None
    try:
        debut = dt.datetime.strptime(depose, _FORMAT_HORODATAGE)
    except ValueError:
        return None
    return (maintenant - debut).total_seconds() / 3600


def orphelins_a_signaler(client_id: str, maintenant: dt.datetime, delai_heures: int = DELAI_ALERTE_HEURES) -> list[dict]:
    """Rapports seuls depuis plus de `delai_heures`, et pas encore signalés.
    Le drapeau `alerte_envoyee` évite de ré-alerter à chaque cycle du service :
    un incident se signale une fois, pas toutes les cinq minutes."""
    a_signaler = []
    for etat in lister(client_id):
        if est_complet(etat) or etat.get("alerte_envoyee"):
            continue
        age = _age_heures(etat, maintenant)
        if age is not None and age >= delai_heures:
            a_signaler.append(etat)
    return a_signaler


def marquer_echec(client_id: str, cle: str, motif: str, horodatage: str) -> bool:
    """Mémorise pourquoi la consolidation d'une paire complète a échoué, et
    renvoie True si ce motif diffère du précédent.

    Sert à ne notifier qu'une fois par cause : une paire complète en échec est
    retentée à chaque cycle (la correction se fait dans le référentiel, pas
    dans le sas), et répéter le même mail toutes les cinq minutes noierait le
    signal. Un motif qui change, en revanche, mérite d'être annoncé — il veut
    dire qu'on a avancé, ou régressé."""
    etat = _lire_etat(client_id, cle)
    if etat is None:
        return False
    precedent = (etat.get("derniere_erreur") or {}).get("motif")
    etat["derniere_erreur"] = {"motif": motif, "horodatage": horodatage}
    _ecrire_etat(client_id, cle, etat)
    return precedent != motif


def paires_en_echec(client_id: str) -> list[dict]:
    """Paires complètes toujours dans le sas : leur consolidation a échoué, et
    rien ne les relancerait sans ça — le traitement n'est déclenché que par
    l'arrivée d'un rapport, or les deux sont déjà là."""
    return [etat for etat in lister(client_id) if est_complet(etat)]


def marquer_signale(client_id: str, cle: str) -> None:
    etat = _lire_etat(client_id, cle)
    if etat is not None:
        etat["alerte_envoyee"] = True
        _ecrire_etat(client_id, cle, etat)


def purger_expires(client_id: str, maintenant: dt.datetime, retention_jours: int = RETENTION_JOURS) -> list[str]:
    """Abandonne les clés incomplètes trop anciennes et renvoie leurs clés.
    Une paire complète n'est jamais purgée ici : elle est consommée puis
    retirée par le traitement, un reste complet signalerait un incident
    qu'il vaut mieux laisser visible."""
    purgees = []
    for etat in lister(client_id):
        if est_complet(etat):
            continue
        age = _age_heures(etat, maintenant)
        if age is not None and age >= retention_jours * 24:
            retirer(client_id, etat["cle"])
            purgees.append(etat["cle"])
    return purgees
