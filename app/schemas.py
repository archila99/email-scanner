from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


ApplicationStatus = Literal["rejected", "interview", "offer", "pending"]


class TrackedApplicationCreate(BaseModel):
    company: str
    role: str
    company_domain: Optional[str] = None
    resume_version_used: Optional[str] = None


class TrackedApplicationRead(BaseModel):
    id: int
    company: str
    role: str
    company_domain: Optional[str] = None
    resume_version_used: Optional[str] = None
    status: ApplicationStatus
    created_at: dt.datetime
    updated_at: dt.datetime
    last_response_at: Optional[dt.datetime]

    model_config = ConfigDict(from_attributes=True)


class IngestRunResponse(BaseModel):
    processed_message_ids: list[str]
    ingested_count: int
    classified_count: int


class ApplicationEventRead(BaseModel):
    id: int
    application_id: int
    event_type: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    occurred_at: dt.datetime
    payload_json: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

