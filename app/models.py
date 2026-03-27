from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel


class ApplicationStatus(str):
    rejected = "rejected"
    interview = "interview"
    offer = "offer"
    pending = "pending"


class TrackedApplication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company: str = Field(index=True)
    role: str = Field(index=True)
    # Optional domain used to match emails that come from the company's sending infrastructure.
    # Example: "jobs.acme.com" or "acme.com"
    company_domain: Optional[str] = Field(default=None, index=True)

    # resume version selected for the application (user-provided)
    resume_version_used: Optional[str] = None

    status: str = Field(default=ApplicationStatus.pending, index=True)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    last_response_at: Optional[dt.datetime] = None


class IngestedEmail(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    provider_message_id: str = Field(index=True, unique=True)
    thread_id: Optional[str] = Field(index=True)

    from_address: Optional[str] = None
    from_domain: Optional[str] = Field(index=True)
    subject: Optional[str] = None
    body_excerpt: Optional[str] = None

    received_at: Optional[dt.datetime] = Field(index=True)

    job_score: Optional[int] = None
    detector_version: str = "keyword-detector-v1"

    classification: Optional[str] = Field(index=True)  # rejected/interview/offer/pending
    classifier_confidence: Optional[float] = None
    extracted_company: Optional[str] = Field(default=None, index=True)
    extracted_role: Optional[str] = Field(default=None, index=True)
    extraction_source: Optional[str] = Field(default=None, index=True)  # keyword/ollama
    matched_application_id: Optional[int] = Field(default=None, foreign_key="trackedapplication.id")

    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class ApplicationEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="trackedapplication.id", index=True)

    event_type: str = Field(index=True)  # status_changed/followup_due/notify_created/etc.
    from_status: Optional[str] = None
    to_status: Optional[str] = None

    occurred_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    payload_json: Optional[str] = None

