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


class JobApplicationEntities(SQLModel, table=True):
    """
    Grouped job application "entity" (per employer/role), derived from events in JobApplications.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    company_name: str = Field(index=True)
    company_domain: Optional[str] = Field(default=None, index=True)
    role: Optional[str] = Field(default=None, index=True)

    # applied | interviewing | offered | rejected | unknown
    status: str = Field(default="applied", index=True)

    email_count: int = Field(default=0, index=True)
    confidence_score: Optional[float] = Field(default=None)

    # rule_based | ml | llm
    created_by: str = Field(default="rule_based", index=True)

    last_event_type: Optional[str] = Field(default=None, index=True)

    first_email_date: dt.datetime = Field(index=True)
    last_email_date: dt.datetime = Field(index=True)

    created_at: dt.datetime = Field(default_factory=_utc_now, index=True)
    last_updated_at: dt.datetime = Field(default_factory=_utc_now, index=True)


class JobApplicationEntityEmails(SQLModel, table=True):
    entity_id: int = Field(foreign_key="jobapplicationentities.id", primary_key=True)
    email_id: int = Field(foreign_key="emails.id", primary_key=True)


class Reminders(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="jobapplicationentities.id", index=True)

    # followup (extensible later)
    type: str = Field(default="followup", index=True)
    due_date: dt.datetime = Field(index=True)

    # pending | done
    status: str = Field(default="pending", index=True)
    generated_text: Optional[str] = None

    created_at: dt.datetime = Field(default_factory=_utc_now, index=True)
