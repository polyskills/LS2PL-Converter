"""Tests de core.history_store : purge au-delà de MAX_HISTORIQUE_CONVERSIONS
et calcul du nombre de jours depuis la dernière conversion réussie."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.client_store import CLIENTS_DIR, create_client
from core.converter import ConversionResult
from core.history_store import (
    MAX_HISTORIQUE_CONVERSIONS,
    echecs_apres_derniere_reussite,
    jours_depuis_derniere_conversion_reussie,
    list_history,
    record_conversion,
)
from core.timezone import now_local


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def _res(point_de_vente="REST", statut_ok=True) -> ConversionResult:
    return ConversionResult(
        point_de_vente=point_de_vente,
        source_filename="export.xlsx",
        lignes=[{"Date": "10/08/26", "Numéro de pièce": "LS-100826-REST"}],
        ca_ht_source=100.0,
        ca_ht_genere=100.0,
        tva_source=10.0,
        ttc_source=110.0,
        total_debit=110.0,
        total_credit=110.0,
        ecart_calcule=0.0,
        ecart_report_declare=0.0,
        avertissements=[],
        erreurs=[] if statut_ok else ["compte manquant"],
    )


def _record(client_id, n, statut_ok=True):
    for i in range(n):
        record_conversion(
            client_id,
            _res(statut_ok=statut_ok),
            source_bytes=b"source",
            csv_bytes=b"csv",
            horodatage=f"2026-01-{(i % 28) + 1:02d} 10:00:00",
        )


def test_purge_ne_conserve_que_les_dernieres():
    client = create_client("Test Historique")
    _record(client["id"], MAX_HISTORIQUE_CONVERSIONS + 10)

    entries = list_history(client["id"])
    assert len(entries) == MAX_HISTORIQUE_CONVERSIONS


def test_purge_supprime_les_fichiers_des_entrees_purgees():
    client = create_client("Test Historique Fichiers")
    premiere = record_conversion(
        client["id"], _res(), source_bytes=b"source", csv_bytes=b"csv", horodatage="2026-01-01 08:00:00"
    )
    chemin_source = premiere["fichier_source_chemin"]
    chemin_genere = premiere["fichier_genere_chemin"]
    assert os.path.exists(chemin_source)
    assert os.path.exists(chemin_genere)

    _record(client["id"], MAX_HISTORIQUE_CONVERSIONS)  # pousse la première hors fenêtre

    assert not os.path.exists(chemin_source)
    assert not os.path.exists(chemin_genere)


def test_jours_depuis_derniere_conversion_reussie_aucune_conversion():
    assert jours_depuis_derniere_conversion_reussie([]) is None


def test_jours_depuis_derniere_conversion_reussie_ignore_les_echecs():
    aujourdhui = now_local().strftime("%Y-%m-%d")
    entries = [
        {"statut": "ERREUR", "horodatage": f"{aujourdhui} 09:00:00"},
        {"statut": "OK", "horodatage": "2026-01-01 09:00:00"},
    ]
    jours = jours_depuis_derniere_conversion_reussie(entries)
    assert jours is not None and jours > 0  # ignore l'échec du jour, retombe sur le succès plus ancien


def test_jours_depuis_derniere_conversion_reussie_aujourdhui():
    aujourdhui = now_local().strftime("%Y-%m-%d")
    entries = [{"statut": "OK", "horodatage": f"{aujourdhui} 09:00:00"}]
    assert jours_depuis_derniere_conversion_reussie(entries) == 0


def test_echecs_apres_derniere_reussite_signale_un_echec_plus_recent():
    # Scénario du bug rapporté : succès à 14:15:35, échec juste après à 14:15:36
    # (même jour) — jours_depuis_derniere_conversion_reussie affiche "aujourd'hui"
    # en vert, ce qui serait trompeur seul : echecs_apres_derniere_reussite doit
    # remonter cet échec plus récent malgré le succès du jour même.
    entries = [
        {"statut": "ERREUR", "horodatage": "2026-08-18 14:15:36", "point_de_vente": "RESTAURANT"},
        {"statut": "OK", "horodatage": "2026-08-18 14:15:35", "point_de_vente": "RESTAURANT"},
    ]
    echecs = echecs_apres_derniere_reussite(entries)
    assert len(echecs) == 1
    assert echecs[0]["horodatage"] == "2026-08-18 14:15:36"


def test_echecs_apres_derniere_reussite_ignore_les_echecs_anterieurs():
    entries = [
        {"statut": "OK", "horodatage": "2026-08-18 14:15:35", "point_de_vente": "RESTAURANT"},
        {"statut": "ERREUR", "horodatage": "2026-08-17 09:00:00", "point_de_vente": "RESTAURANT"},
    ]
    assert echecs_apres_derniere_reussite(entries) == []


def test_echecs_apres_derniere_reussite_sans_aucune_reussite():
    entries = [{"statut": "ERREUR", "horodatage": "2026-08-18 14:15:36", "point_de_vente": "RESTAURANT"}]
    assert len(echecs_apres_derniere_reussite(entries)) == 1
