"""
Client HTTP minimal pour Microsoft Graph, en flux "application" (client
credentials, sans utilisateur connecté) — adapté à un service qui tourne sans
supervision humaine, sur une boîte mail hébergée dans le tenant M365 du
CLIENT plutôt que celui de Polyskills.

Volontairement pas de SDK Graph complet (poids, complexité pour ce qu'on en
fait) : seuls les appels REST réellement utilisés par le service de fetch
sont couverts. Une seule app Azure AD, enregistrée côté Polyskills en
multi-tenant, est réutilisée pour tous les clients : c'est le tenant_id passé
à la construction qui détermine quelle autorité émet le jeton, et donc quel
tenant est interrogé — après consentement admin donné une fois par chaque
client sur cette app.
"""
from __future__ import annotations

import base64

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]  # portée fixe en flux "application"


class GraphError(Exception):
    """Levée sur toute erreur d'authentification ou réponse HTTP non 2xx de Graph."""


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self._tenant_id = tenant_id
        self._app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )

    def _access_token(self) -> str:
        result = self._app.acquire_token_silent(_SCOPE, account=None)
        if not result:
            result = self._app.acquire_token_for_client(scopes=_SCOPE)
        if not result or "access_token" not in result:
            detail = (result or {}).get("error_description", "réponse vide")
            raise GraphError(
                f"Authentification Graph échouée pour le tenant {self._tenant_id} : {detail}"
            )
        return result["access_token"]

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise GraphError(f"{method} {url} -> HTTP {resp.status_code} : {resp.text[:500]}")
        return resp

    def list_unread_with_attachments(self, mailbox: str, folder: str = "inbox", top: int = 25) -> list[dict]:
        """Mails non lus avec pièce jointe, les plus récents en premier. La
        boîte reçoit sur plusieurs adresses dédiées (une par point de vente) :
        c'est `toRecipients` sur chaque message, pas cet appel, qui distingue
        lesquelles (cf. core.email_ingest.identifier_source)."""
        url = (
            f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{folder}/messages"
            "?$filter=isRead eq false and hasAttachments eq true"
            "&$select=id,subject,toRecipients,receivedDateTime"
            f"&$top={top}&$orderby=receivedDateTime desc"
        )
        return self._request("GET", url).json().get("value", [])

    def list_file_attachments(self, mailbox: str, message_id: str) -> list[dict]:
        """Ne renvoie que les pièces jointes fichier (pas les items/mails
        imbriqués), avec leur contenu décodé en bytes prêt à l'emploi."""
        url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/attachments"
        items = self._request("GET", url).json().get("value", [])
        out = []
        for item in items:
            if item.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            out.append(
                {
                    "name": item.get("name", ""),
                    "content": base64.b64decode(item["contentBytes"]),
                }
            )
        return out

    def mark_as_read(self, mailbox: str, message_id: str) -> None:
        url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}"
        self._request("PATCH", url, json={"isRead": True})

    def send_mail(
        self,
        mailbox: str,
        subject: str,
        body_html: str,
        to_addresses: list[str],
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> None:
        """Envoie depuis `mailbox` (Mail.Send requis sur cette boîte). Les
        pièces jointes générées (source + CSV) restent petites (exports
        journaliers) : pas besoin des sessions d'upload par chunks de Graph,
        réservées aux fichiers > 3 Mo."""
        message = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_addresses],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": name,
                    "contentBytes": base64.b64encode(content).decode("ascii"),
                }
                for name, content in (attachments or [])
            ],
        }
        url = f"{GRAPH_BASE}/users/{mailbox}/sendMail"
        self._request("POST", url, json={"message": message, "saveToSentItems": True})
