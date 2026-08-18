"""
Tests de l'orchestration du fetch mail (core.email_poller), sans réseau ni
tenant Azure réel : un faux client Graph (même surface que
core.graph_client.GraphClient) simule les réponses Microsoft Graph.
"""
import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from openpyxl import Workbook

from core.client_store import CLIENTS_DIR, create_client
from core.email_poller import traiter_client
from core.history_store import list_history
from core.mapping_store import DEFAULT_MAPPINGS, load_mappings, save_mappings, set_pdv_adresse_email


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    yield
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)


def _build_sample_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    rows = [
        ["Références comptables", "Quantité", "Total", "Rabais", "Total TTC Moins les rabais",
         "Montant taxé", "TVA 10%", "Total taxes", "%", "Total HT"],
        ["Cuisine - Entrée", 10, 17, None, 17, 17, 1.5455, 1.5455, 6.5, 15.4545],
        ["Total EUR", 10, 17, None, 17, 17, 1.5455, 1.5455, 100, 15.4545],
        [None] * 10,
        ["Modes de paiement", "Montant (Moins retour)"] + [None] * 8,
        ["Carte bleue", 17] + [None] * 8,
        ["Total EUR", 17] + [None] * 8,
        ["Total taxes EUR", 1.5455] + [None] * 8,
        ["Total EUR (Moins les taxes)", 15.4545] + [None] * 8,
    ]
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeGraph:
    """Simule les méthodes de core.graph_client.GraphClient utilisées par
    l'orchestration, en mémoire. `messages` est mutable pour composer un
    scénario avant d'appeler traiter_client()."""

    def __init__(self):
        self.messages = []  # list[{"id", "toRecipients", "attachments": [(name, bytes)]}]
        self.marked_read = []
        self.sent = []  # list[dict(subject, body_html, to_addresses, attachments)]

    def list_unread_with_attachments(self, mailbox, folder="inbox", top=25):
        return [{"id": m["id"], "toRecipients": m["toRecipients"]} for m in self.messages]

    def list_file_attachments(self, mailbox, message_id):
        msg = next(m for m in self.messages if m["id"] == message_id)
        return [{"name": name, "content": content} for name, content in msg["attachments"]]

    def mark_as_read(self, mailbox, message_id):
        self.marked_read.append(message_id)

    def send_mail(self, mailbox, subject, body_html, to_addresses, attachments=None):
        self.sent.append(
            {"subject": subject, "body_html": body_html, "to_addresses": to_addresses, "attachments": attachments}
        )


def _client_pret(adresse: str, code_pdv: str = "REST") -> dict:
    """Un client avec le référentiel d'exemple (REST déjà entièrement mappé,
    cf. DEFAULT_MAPPINGS) et une adresse mail dédiée sur le point de vente REST."""
    client = create_client("Test Poller")
    save_mappings(client["id"], DEFAULT_MAPPINGS)
    set_pdv_adresse_email(client["id"], code_pdv, adresse)
    client["email_tenant_id"] = "tenant-test"
    client["email_mailbox"] = "boite@client.example.com"
    return client


def test_client_sans_config_mail_ignore():
    client = create_client("Sans fetch")
    graph = FakeGraph()
    graph.messages.append({"id": "m1", "toRecipients": [], "attachments": []})
    traiter_client(graph, client)
    assert graph.marked_read == []  # jamais interrogé : pas de tenant/boîte configurés


def test_mail_avec_adresse_connue_convertit_et_repond():
    client = _client_pret("rest@client.example.com")
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "rest@client.example.com"}}],
            "attachments": [("client_rest_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    traiter_client(graph, client)

    assert graph.marked_read == ["m1"]
    assert len(graph.sent) == 1
    assert "REST" in graph.sent[0]["subject"]
    assert graph.sent[0]["to_addresses"] == ["rest@client.example.com"]  # à l'adresse d'origine, pas à l'alerte interne
    assert len(graph.sent[0]["attachments"]) == 2  # fichier source + CSV généré

    historique = list_history(client["id"])
    assert len(historique) == 1
    assert historique[0]["statut"] == "OK"
    assert historique[0]["point_de_vente"] == "REST"


def test_mail_avec_adresse_resultat_configuree_repond_a_cette_adresse():
    # adresse_resultat renseignée sur le point de vente : le résultat doit
    # partir vers elle, pas vers l'adresse de réception d'origine.
    client = _client_pret("rest@client.example.com")
    m = load_mappings(client["id"])
    for pdv in m["points_de_vente"]:
        if pdv["code"] == "REST":
            pdv["adresse_resultat"] = "compta@client.example.com"
    save_mappings(client["id"], m)

    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "rest@client.example.com"}}],
            "attachments": [("client_rest_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    traiter_client(graph, client)

    assert len(graph.sent) == 1
    assert graph.sent[0]["to_addresses"] == ["compta@client.example.com"]


def test_mail_avec_adresse_inconnue_alerte_sans_convertir():
    client = _client_pret("rest@client.example.com")
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "adresse-non-configuree@client.example.com"}}],
            "attachments": [("mystere_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    os.environ["LSPENNYLANE_ALERTE_INTERNE"] = "alerte@polyskills.fr"
    try:
        traiter_client(graph, client)
    finally:
        del os.environ["LSPENNYLANE_ALERTE_INTERNE"]

    assert graph.marked_read == ["m1"]
    assert len(graph.sent) == 1
    assert graph.sent[0]["to_addresses"] == ["alerte@polyskills.fr"]
    assert "non identifié" in graph.sent[0]["subject"]
    assert list_history(client["id"]) == []  # rien archivé : jamais entré dans le pipeline de conversion


def test_mail_avec_mapping_manquant_alerte_en_interne_jamais_au_client():
    # Point de vente REST rattaché à l'adresse, mais référentiel vide : la
    # conversion doit échouer proprement plutôt que d'envoyer un CSV faux au client.
    client = create_client("Test Poller Incomplet")
    set_pdv_adresse_email(client["id"], "REST", "rest@client.example.com")
    from core.mapping_store import EMPTY_MAPPINGS
    save_mappings(client["id"], {**EMPTY_MAPPINGS, "points_de_vente": [{"code": "REST", "libelle": "REST", "adresse_email": "rest@client.example.com"}]})
    client["email_tenant_id"] = "tenant-test"
    client["email_mailbox"] = "boite@client.example.com"

    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "rest@client.example.com"}}],
            "attachments": [("client_rest_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    os.environ["LSPENNYLANE_ALERTE_INTERNE"] = "alerte@polyskills.fr"
    try:
        traiter_client(graph, client)
    finally:
        del os.environ["LSPENNYLANE_ALERTE_INTERNE"]

    assert graph.marked_read == ["m1"]
    assert len(graph.sent) == 1
    assert graph.sent[0]["to_addresses"] == ["alerte@polyskills.fr"]  # jamais au client
    assert "Échec de conversion" in graph.sent[0]["subject"]

    historique = list_history(client["id"])
    assert len(historique) == 1
    assert historique[0]["statut"] == "ERREUR"  # archivé même en échec
