from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from app.email.gmail_provider import RawEmail


def _strip_html(html: str) -> str:
    # Best-effort stripping; good enough for keyword matching.
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


@dataclass(frozen=True)
class NormalizedEmail:
    provider_message_id: str
    thread_id: str | None
    from_address: str | None
    from_domain: str | None
    subject: str | None
    body_excerpt: str
    received_at: dt.datetime | None
    body_for_detection: str  # normalized full text for detectors


def preprocess_email(raw: RawEmail, body_excerpt_chars: int = 600) -> NormalizedEmail:
    body = raw.body or ""
    # If it looks like HTML, strip tags for matching.
    if "<html" in body.lower() or "<body" in body.lower() or re.search(r"(?is)<[a-z][\s\S]*>", body):
        body = _strip_html(body)

    body = normalize_text(body)
    # Gmail templates often contain HTML entities (&nbsp; etc). Decode them
    # so regex matching for role/company works reliably.
    body = html.unescape(body)
    body_excerpt = body[:body_excerpt_chars].strip()

    received_at: dt.datetime | None = None
    if raw.received_at:
        try:
            received_at = parsedate_to_datetime(raw.received_at)
        except Exception:
            received_at = None

    return NormalizedEmail(
        provider_message_id=raw.provider_message_id,
        thread_id=raw.thread_id,
        from_address=raw.from_address,
        from_domain=raw.from_domain.lower() if raw.from_domain else None,
        subject=(raw.subject.strip() if raw.subject else None),
        body_excerpt=body_excerpt,
        received_at=received_at,
        body_for_detection=body,
    )

