from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Emails(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str
    body: Optional[str] = None
    sender: str
    received_at: dt.datetime = Field(index=True)

    # Optional raw payload (JSON string) if you want to preserve it
    raw_data: Optional[str] = None

    # Final application-related classification for this email (nullable).
    # Null means the email was imported but not considered one of the tracked
    # application states in this simplified app.
    classification: Optional[str] = Field(default=None, index=True)


class JobApplications(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email_id: int = Field(foreign_key="emails.id", index=True)

    # Application-only tracked type: application / rejection / interview / offer
    type: str = Field(index=True)
    matched_role: Optional[str] = None
    matched_company: Optional[str] = None

    created_at: dt.datetime = Field(default_factory=_utc_now, index=True)
