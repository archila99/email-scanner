from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Literal


JobType = Literal["application", "rejection", "interview", "offer"]


@dataclass(frozen=True)
class SubjectClassification:
    type: Optional[JobType]
    confidence: float


_RE_APPLICATION = re.compile(
    r"(?i)\b(your application|we'?ve received|thank you for your application|thank you for applying|thanks for applying)\b"
)
_RE_REJECTION = re.compile(
    r"(?i)\b(unfortunately|regret to inform|not move forward|not moving forward|not proceed|not progressing|application update)\b"
)
_RE_INTERVIEW = re.compile(r"(?i)\b(interview|invitation)\b")
_RE_OFFER = re.compile(r"(?i)\b(offer|congratulations|pleased to offer)\b")


def classify_from_subject(subject: str) -> SubjectClassification:
    s = (subject or "").strip()
    if not s:
        return SubjectClassification(type=None, confidence=0.0)

    if _RE_APPLICATION.search(s):
        return SubjectClassification(type="application", confidence=0.9)
    if _RE_REJECTION.search(s):
        return SubjectClassification(type="rejection", confidence=0.88)
    if _RE_INTERVIEW.search(s):
        return SubjectClassification(type="interview", confidence=0.9)
    if _RE_OFFER.search(s):
        return SubjectClassification(type="offer", confidence=0.9)

    return SubjectClassification(type=None, confidence=0.2)

