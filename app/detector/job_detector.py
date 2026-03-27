from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.email.preprocess import NormalizedEmail


def _to_list(csv_or_list: str) -> list[str]:
    return [x.strip().lower() for x in csv_or_list.split(",") if x.strip()]


@dataclass(frozen=True)
class DetectionResult:
    is_job_related: bool
    score: int
    features: dict[str, int]


def detect_job_related(email: NormalizedEmail) -> DetectionResult:
    """
    Keyword/domain detector (default).

    Returns a score that downstream classification can use.
    """

    text = (email.subject or "") + "\n" + email.body_for_detection
    text_l = text.lower()

    features: dict[str, int] = {
        "job_keywords": 0,
        "outcome_keywords": 0,
        "resume_keywords": 0,
        "invitation_keywords": 0,
        "noise_penalty": 0,
    }

    # Noise penalties (ads/newsletters/etc.)
    sender_domain_blacklist = _to_list(settings.sender_domain_blacklist)
    for banned in sender_domain_blacklist:
        if email.from_domain and email.from_domain.endswith(banned):
            features["noise_penalty"] += 25
            break

    for kw in _to_list(settings.subject_noise_keywords):
        if not kw:
            continue
        subject_hit = email.subject and email.subject.lower().find(kw) >= 0
        body_hit = email.body_for_detection and email.body_for_detection.lower().find(kw) >= 0
        if subject_hit or body_hit:
            features["noise_penalty"] += 10

    # Positive signals (job context)
    job_keywords = [
        "application",
        "candidate",
        "recruiter",
        "position",
        "role",
        "job",
        "hiring",
    ]
    outcome_keywords = [
        "rejected",
        "not selected",
        "decline",
        "unfortunately",
        "offer",
        "compensation",
        "salary",
        "employment",
    ]
    invitation_keywords = [
        "interview",
        "screen",
        "call",
        "technical interview",
        "zoom",
        "hr interview",
    ]
    resume_keywords = ["resume", "cv", "curriculum vitae"]

    for kw in job_keywords:
        if kw in text_l:
            features["job_keywords"] += 3

    for kw in invitation_keywords:
        if kw in text_l:
            features["invitation_keywords"] += 6

    for kw in outcome_keywords:
        if kw in text_l:
            features["outcome_keywords"] += 7

    for kw in resume_keywords:
        if kw in text_l:
            features["resume_keywords"] += 4

    # Anchor: application submission/receipt confirmations are strong job-related signals.
    anchor_keywords = [
        "your application has been received",
        "we have received your application",
        "has been received",
        "thank you for applying",
        "successfully completed",
        "successfully submitted",
        "your application for",
        "next steps",
    ]
    for kw in anchor_keywords:
        if kw in text_l:
            features["job_keywords"] += 10

    # Hard noise filtering: if this looks like an ad/newsletter/marketing blast,
    # avoid classifying it as job-related unless we also see strong anchor/job context.
    hard_anchor_hit = any(kw in text_l for kw in anchor_keywords)
    noise_words = _to_list(settings.subject_noise_keywords)
    body_noise_hit = any(kw in (email.body_for_detection or "").lower() for kw in noise_words if kw)
    if body_noise_hit and not hard_anchor_hit:
        features["noise_penalty"] += 40

    score = (
        features["job_keywords"]
        + features["outcome_keywords"]
        + features["resume_keywords"]
        + features["invitation_keywords"]
        - features["noise_penalty"]
    )

    is_job_related = score >= settings.job_detector_min_score
    return DetectionResult(is_job_related=is_job_related, score=max(0, score), features=features)

