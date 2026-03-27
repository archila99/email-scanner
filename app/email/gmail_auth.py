from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import settings


def _get_scopes() -> Sequence[str]:
    # Read-only for MVP. Automation “sending” can be added later by extending scope.
    return ["https://www.googleapis.com/auth/gmail.readonly"]


def build_gmail_service():
    """
    Build an authenticated Gmail API service (OAuth installed app flow).

    Expected files:
    - `settings.google_client_secret_file`: OAuth client secret JSON
    - `settings.google_token_file`: persisted user token JSON (generated on first run)
    """

    client_secret = Path(settings.google_client_secret_file)
    token_file = Path(settings.google_token_file)

    if not client_secret.exists():
        raise RuntimeError(
            f"Missing Gmail OAuth client secret file: {client_secret}. "
            "Set GOOGLE_CLIENT_SECRET_FILE or copy client_secret.json."
        )

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), _get_scopes())

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), _get_scopes())
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)

