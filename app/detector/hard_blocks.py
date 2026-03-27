from __future__ import annotations

from app.config import settings
from app.email.preprocess import NormalizedEmail


def _to_list(csv: str) -> list[str]:
    return [x.strip().lower() for x in (csv or "").split(",") if x.strip()]


def is_hard_blocked(email: NormalizedEmail) -> bool:
    """
    Fast deterministic noise filter.
    If this returns True, we skip LLM + keyword classification.
    """

    from_domain = (email.from_domain or "").lower()
    subject = (email.subject or "").lower()
    body = (email.body_for_detection or "").lower()

    # Job boards / aggregators often send recommendations that are not actual applications.
    # Block those unless we see clear "you applied / application received" evidence.
    if from_domain.endswith("jobs.totaljobsmail.com"):
        applied_signals = (
            "your application" in body
            or "we have received your application" in body
            or "application has been received" in body
            or "thank you for applying" in body
            or "successfully submitted" in body
            or "successfully completed" in body
            or "you applied" in body
            or "you have applied" in body
        )
        recommendation_signals = (
            "our recommendation" in subject
            or "recommended jobs" in subject
            or "jobs you may like" in subject
            or "based on your profile" in subject
            or "recommendation" in subject
        )
        if recommendation_signals and not applied_signals:
            return True

    # Domain blacklist
    for banned in _to_list(settings.sender_domain_blacklist):
        if banned and from_domain.endswith(banned):
            return True

    # Marketing/newsletter patterns
    noise_words = _to_list(settings.subject_noise_keywords)
    if any(w in subject for w in noise_words if w) and "application" not in subject:
        return True
    if any(w in body for w in noise_words if w) and "application" not in body:
        return True

    # Explicit unsubscribe is nearly always non-job-content.
    if "unsubscribe" in body and "application" not in body and "candidate" not in body:
        return True

    return False

