"""Integração com a Gmail API para leitura de não lidos e marcação seletiva de newsletters."""

import base64
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.html_cleaner import clean_email_html
from src.schemas import RawEmail

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def _extract_body_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Extrai (html_body, text_body) percorrendo partes MIME recursivamente."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if body_data:
        decoded = _decode_base64url(body_data)
        if mime_type == "text/html":
            return decoded, ""
        if mime_type == "text/plain":
            return "", decoded

    html_acc: list[str] = []
    text_acc: list[str] = []
    for part in payload.get("parts", []):
        h, t = _extract_body_from_payload(part)
        if h:
            html_acc.append(h)
        if t:
            text_acc.append(t)

    return "\n".join(html_acc), "\n".join(text_acc)


class GmailService:
    """Cliente enxuto da Gmail API usando OAuth2 refresh_token."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=GMAIL_SCOPES,
        )
        creds.refresh(Request())
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def fetch_unread_emails(self, query: str, max_results: int = 15) -> list[RawEmail]:
        """Busca e-mails não lidos e retorna o conteúdo já limpo em Python puro."""
        response = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = response.get("messages", [])
        emails: list[RawEmail] = []

        for msg_meta in messages:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="full")
                .execute()
            )
            payload = msg.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            html_body, text_body = _extract_body_from_payload(payload)
            clean_body = (
                clean_email_html(html_body) if html_body else clean_email_html(text_body)
            )
            if not clean_body:
                continue

            emails.append(
                RawEmail(
                    message_id=msg["id"],
                    sender=headers.get("from", "Desconhecido"),
                    subject=headers.get("subject", "(Sem assunto)"),
                    clean_body=clean_body,
                )
            )

        return emails

    def mark_as_read(self, message_ids: list[str]) -> None:
        """Remove a label UNREAD exclusivamente dos IDs informados."""
        if not message_ids:
            return
        self._service.users().messages().batchModify(
            userId="me",
            body={"ids": message_ids, "removeLabelIds": ["UNREAD"]},
        ).execute()
