from __future__ import annotations

from fastapi import Depends

from app.db import get_session
from app.email.gmail_auth import build_gmail_service
from app.email.gmail_provider import GmailProvider


def get_db():
    yield from get_session()


def get_gmail_provider():
    service = build_gmail_service()
    return GmailProvider(service)

