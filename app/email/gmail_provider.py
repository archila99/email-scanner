from __future__ import annotations

import base64
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Optional

from googleapiclient.discovery import Resource

from app.config import settings


@dataclass(frozen=True)
class RawEmail:
    provider_message_id: str
    thread_id: Optional[str]
    from_address: Optional[str]
    from_domain: Optional[str]
    subject: Optional[str]
    body: str
    received_at: Optional[str]  # ISO-ish string from Gmail


def _decode_base64url(data: str) -> str:
    # Gmail API uses base64url.
    missing_padding = len(data) % 4
    if missing_padding:
        data += "=" * (4 - missing_padding)
    decoded = base64.urlsafe_b64decode(data.encode("utf-8"))
    return decoded.decode("utf-8", errors="replace")


def _walk_parts(payload: dict) -> str:
    # Try to find best-effort plain text; fall back to decoded HTML.
    parts = [payload]
    while parts:
        part = parts.pop()
        if part.get("parts"):
            parts.extend(part["parts"])
            continue
        body = part.get("body") or {}
        data = body.get("data")
        mime_type = part.get("mimeType") or ""
        if data:
            decoded = _decode_base64url(data)
            # Prefer text/plain parts.
            if mime_type.startswith("text/plain"):
                return decoded
            # Otherwise keep first non-empty.
            if decoded.strip():
                return decoded
    return ""


class GmailProvider:
    def __init__(self, service: Resource):
        self._service = service

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        res = (
            self._service.users()
            .messages()
            .list(userId=settings.gmail_user_id, q=query, maxResults=max_results)
            .execute()
        )
        messages = res.get("messages") or []
        return [m["id"] for m in messages if "id" in m]

    def get_message(self, message_id: str) -> RawEmail:
        msg = (
            self._service.users()
            .messages()
            .get(userId=settings.gmail_user_id, id=message_id, format="full")
            .execute()
        )

        headers = {h.get("name", "").lower(): h.get("value") for h in (msg.get("payload", {}).get("headers") or [])}
        from_header = headers.get("from")
        name, addr = parseaddr(from_header or "")
        from_domain = addr.split("@", 1)[-1].lower() if "@" in addr else None

        subject = headers.get("subject")
        received_at = headers.get("date")

        body = ""
        payload = msg.get("payload") or {}
        if payload:
            body = _walk_parts(payload)

        return RawEmail(
            provider_message_id=msg["id"],
            thread_id=msg.get("threadId"),
            from_address=addr or None,
            from_domain=from_domain,
            subject=subject,
            body=body or "",
            received_at=received_at,
        )

