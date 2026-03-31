from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Literal


JobType = Literal["application", "rejection", "interview", "offer"]


@dataclass(frozen=True)
class BodyClassification:
    type: Optional[JobType]
    confidence: float


_RE_APPLICATION = re.compile(
    r"(?i)\b(thank you for applying|thanks for applying|your application|we received your application|application has been received)\b"
)
_RE_REJECTION = re.compile(
    r"(?i)\b(regret to inform|not move forward|not moving forward|not proceed|not progressing|we['’]ve decided not to move forward)\b|unfortunately[\s\S]{0,120}application"
)
_RE_INTERVIEW = re.compile(r"(?i)\b(invite you to interview|interview invitation|schedule (an )?interview|your interview|availability for interview)\b")
_RE_OFFER = re.compile(r"(?i)\b(pleased to offer|offer of employment|congratulations)\b")
_RE_RECOMMENDATION_NOISE = re.compile(
    r"(?i)\b(our recommendation|recommended jobs|jobs you may like|job alert|career[- ]ready|opportunities waiting for you|saved job search|new jobs posted)\b"
)


def classify_from_body(body: str) -> BodyClassification:
    text = (body or "").strip()
    if not text:
        return BodyClassification(type=None, confidence=0.0)

    if _RE_RECOMMENDATION_NOISE.search(text):
        return BodyClassification(type=None, confidence=0.0)

    if _RE_REJECTION.search(text):
        return BodyClassification(type="rejection", confidence=0.93)
    if _RE_APPLICATION.search(text):
        return BodyClassification(type="application", confidence=0.9)
    if _RE_INTERVIEW.search(text):
        return BodyClassification(type="interview", confidence=0.9)
    if _RE_OFFER.search(text):
        return BodyClassification(type="offer", confidence=0.9)

    return BodyClassification(type=None, confidence=0.2)

