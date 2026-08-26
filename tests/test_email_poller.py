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

from core.app_config import APP_CONFIG_PATH
from core.client_store import CLIENTS_DIR, create_client, get_prefixe_mail, set_azure_credentials, set_prefixe_mail
from core.email_poller import _identifiants_azure, traiter_client
from core.history_store import list_history
from core.mapping_store import DEFAULT_MAPPINGS, load_mappings, save_mappings, set_pdv_adresse_email


def _clean():
    shutil.rmtree(CLIENTS_DIR, ignore_errors=True)
    if os.path.exists(APP_CONFIG_PATH):
        os.remove(APP_CONFIG_PATH)


@pytest.fixture(autouse=True)
def _clean_clients_dir():
    _clean()
    yield
    _clean()


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
        return [
            {"id": m["id"], "toRecipients": m["toRecipients"], "internetMessageHeaders": m.get("internetMessageHeaders")}
            for m in self.messages
        ]

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


def test_get_prefixe_mail_par_defaut_sans_reglage():
    assert get_prefixe_mail({"id": "sans-prefixe"}) == "LS2PL"


def test_set_puis_get_prefixe_mail():
    client = create_client("Test Préfixe")
    set_prefixe_mail(client["id"], "ASPP")
    from core.client_store import get_client
    assert get_prefixe_mail(get_client(client["id"])) == "ASPP"


def test_client_sans_config_mail_ignore():
    client = create_client("Sans fetch")
    graph = FakeGraph()
    graph.messages.append({"id": "m1", "toRecipients": [], "attachments": []})
    traiter_client(graph, client)
    assert graph.marked_read == []  # jamais interrogé : pas de tenant/boîte configurés


def test_identifiants_azure_priorite_au_client():
    client = create_client("Test Identifiants")
    set_azure_credentials(client["id"], "client-id-propre", "secret-propre")
    client["azure_client_id"] = "client-id-propre"
    client["azure_client_secret"] = "secret-propre"

    os.environ["LSPENNYLANE_AZURE_CLIENT_ID"] = "client-id-env"
    os.environ["LSPENNYLANE_AZURE_CLIENT_SECRET"] = "secret-env"
    try:
        assert _identifiants_azure(client) == ("client-id-propre", "secret-propre")
    finally:
        del os.environ["LSPENNYLANE_AZURE_CLIENT_ID"]
        del os.environ["LSPENNYLANE_AZURE_CLIENT_SECRET"]


def test_identifiants_azure_repli_sur_variables_environnement():
    client = {"id": "sans-identifiants-propres"}
    os.environ["LSPENNYLANE_AZURE_CLIENT_ID"] = "client-id-env"
    os.environ["LSPENNYLANE_AZURE_CLIENT_SECRET"] = "secret-env"
    try:
        assert _identifiants_azure(client) == ("client-id-env", "secret-env")
    finally:
        del os.environ["LSPENNYLANE_AZURE_CLIENT_ID"]
        del os.environ["LSPENNYLANE_AZURE_CLIENT_SECRET"]


def test_identifiants_azure_aucun_disponible():
    assert _identifiants_azure({"id": "sans-rien"}) is None


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
    assert historique[0]["destinataires_email"] == ["rest@client.example.com"]
    # préfixe par défaut, "LS2PL" sans "Conversion", client_id en MAJUSCULES, tirets simples
    assert graph.sent[0]["subject"].startswith(f"[LS2PL] LS2PL - {client['id'].upper()}/REST - ")

    nom_csv_genere = graph.sent[0]["attachments"][1][0]
    assert nom_csv_genere == f"import_pl_{client['id']}_REST_20260810.csv"


def test_mail_de_succes_utilise_le_prefixe_propre_au_client():
    client = _client_pret("rest@client.example.com")
    client["prefixe_mail"] = "ASPP"
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "rest@client.example.com"}}],
            "attachments": [("client_rest_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    traiter_client(graph, client)

    assert graph.sent[0]["subject"].startswith(f"[ASPP] LS2PL - {client['id'].upper()}/REST - ")


def test_mail_recu_via_alias_identifie_via_en_tete_to_brut():
    # Reproduit le cas réel observé sur le tenant Maison PIC : la boîte
    # partagée reçoit plusieurs adresses dédiées via alias, mais Exchange
    # normalise `toRecipients` vers l'adresse PRINCIPALE de la boîte au lieu
    # de l'alias réellement utilisé par l'expéditeur — seul l'en-tête `To:`
    # brut (internetMessageHeaders) préserve l'alias.
    client = _client_pret("rapport_ls2pl_paris-bar@annesophiepic-paris.com")
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            # toRecipients résolu par Exchange vers la boîte principale, PAS l'alias :
            "toRecipients": [{"emailAddress": {"address": "rapport_ls2pl_paris@annesophiepic-paris.com"}}],
            "internetMessageHeaders": [
                {"name": "To", "value": "rapport_ls2pl_paris-bar@annesophiepic-paris.com"},
            ],
            "attachments": [("export_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    traiter_client(graph, client)

    assert graph.marked_read == ["m1"]
    assert len(graph.sent) == 1  # identifié malgré toRecipients trompeur -> conversion + réponse, pas d'alerte
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


def test_mail_avec_plusieurs_adresses_resultat_separees_par_virgule_ou_point_virgule():
    client = _client_pret("rest@client.example.com")
    m = load_mappings(client["id"])
    for pdv in m["points_de_vente"]:
        if pdv["code"] == "REST":
            pdv["adresse_resultat"] = " compta@client.example.com , direction@client.example.com;autre@client.example.com "
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
    assert graph.sent[0]["to_addresses"] == [
        "compta@client.example.com",
        "direction@client.example.com",
        "autre@client.example.com",
    ]


def test_mail_avec_adresse_inconnue_alerte_en_interne_et_notifie_le_client():
    # Adresse non reconnue : alerte interne ET notification à l'adresse
    # candidate elle-même (aucun client/PDV identifié, donc pas d'adresse
    # « résultat » possible) — utile si une entrée du référentiel a été
    # modifiée par erreur.
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
    assert len(graph.sent) == 2
    interne = next(m for m in graph.sent if m["to_addresses"] == ["alerte@polyskills.fr"])
    assert "non identifié" in interne["subject"]
    client_notif = next(m for m in graph.sent if m["to_addresses"] == ["adresse-non-configuree@client.example.com"])
    assert "Échec" in client_notif["subject"]
    assert list_history(client["id"]) == []  # rien archivé : jamais entré dans le pipeline de conversion


def test_mail_avec_adresse_inconnue_sans_alerte_interne_notifie_quand_meme_le_client(caplog):
    # Sans LSPENNYLANE_ALERTE_INTERNE (cas d'un test local, ex. sur le Mac de
    # Matthieu), le mail ne doit plus échouer en silence complet : au moins
    # un log doit tracer le motif côté interne, et la notification côté
    # client part quand même (elle ne dépend pas de cette variable).
    client = _client_pret("rest@client.example.com")
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "adresse-non-configuree@client.example.com"}}],
            "attachments": [("mystere_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    with caplog.at_level("WARNING"):
        traiter_client(graph, client)

    assert graph.marked_read == ["m1"]
    assert len(graph.sent) == 1  # notification client uniquement, pas d'alerte interne envoyable
    assert graph.sent[0]["to_addresses"] == ["adresse-non-configuree@client.example.com"]
    assert any("non rattachée" in r.message for r in caplog.records)


def test_mail_avec_mapping_manquant_alerte_en_interne_et_le_client():
    # Point de vente REST rattaché à l'adresse, mais référentiel vide : la
    # conversion doit échouer proprement plutôt que d'envoyer un CSV faux au
    # client — mais celui-ci doit quand même être informé de l'échec (sans
    # adresse_resultat configurée, on retombe sur l'adresse de réception).
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
    assert len(graph.sent) == 2
    interne = next(m for m in graph.sent if m["to_addresses"] == ["alerte@polyskills.fr"])
    assert "Échec de conversion" in interne["subject"]
    client_notif = next(m for m in graph.sent if m["to_addresses"] == ["rest@client.example.com"])
    assert "Échec" in client_notif["subject"]
    assert client_notif["subject"].startswith("[LS2PL] ")  # préfixe par défaut, notification client uniquement
    corps = client_notif["body_html"]
    assert "client_rest_business_export_accounting_20260810_20260811.xlsx" in corps  # nom de fichier
    assert "REST" in corps  # point de vente
    assert "Comptes de vente" in corps or "compte" in corps.lower()  # motif de l'échec repris
    assert "Historique" in corps  # invitation à s'y rendre pour corriger et relancer

    historique = list_history(client["id"])
    assert len(historique) == 1
    assert historique[0]["statut"] == "ERREUR"  # archivé même en échec
    assert historique[0]["destinataires_email"] == ["rest@client.example.com"]


def test_notification_echec_inclut_un_lien_si_url_app_configuree():
    from core.app_config import set_url_app

    client = create_client("Test Poller Lien")
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

    set_url_app("https://ls2pl-test.streamlit.app")
    try:
        traiter_client(graph, client)
    finally:
        set_url_app("")

    client_notif = next(m for m in graph.sent if m["to_addresses"] == ["rest@client.example.com"])
    assert "https://ls2pl-test.streamlit.app/historique" in client_notif["body_html"]


def test_mail_de_succes_inclut_le_lien_app_en_pied_de_page():
    from core.app_config import set_url_app

    client = _client_pret("rest@client.example.com")
    graph = FakeGraph()
    graph.messages.append(
        {
            "id": "m1",
            "toRecipients": [{"emailAddress": {"address": "rest@client.example.com"}}],
            "attachments": [("client_rest_business_export_accounting_20260810_20260811.xlsx", _build_sample_xlsx())],
        }
    )

    set_url_app("https://ls2pl-test.streamlit.app")
    try:
        traiter_client(graph, client)
    finally:
        set_url_app("")

    assert "https://ls2pl-test.streamlit.app" in graph.sent[0]["body_html"]


def test_mail_de_succes_sans_pied_de_page_si_url_app_non_configuree():
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

    assert "http" not in graph.sent[0]["body_html"]
