from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

ApplicationEmailType = Literal["application", "rejection", "interview", "offer"]


class EmailRead(BaseModel):
    id: int
    subject: str
    body: Optional[str] = None
    sender: str
    received_at: dt.datetime
    raw_data: Optional[str] = None
    classification: Optional[ApplicationEmailType] = None

    model_config = ConfigDict(from_attributes=True)


class JobApplicationRead(BaseModel):
    id: int
    email_id: int
    type: ApplicationEmailType
    matched_role: Optional[str] = None
    matched_company: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class IngestRunResponse(BaseModel):
    processed_message_ids: list[str]
    ingested_count: int
    classified_count: int

