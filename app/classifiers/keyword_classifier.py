from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.email.preprocess import NormalizedEmail


@dataclass(frozen=True)
class ClassificationResult:
    label: str  # rejected/interview/offer/pending
    confidence: float


def classify_job_outcome(email: NormalizedEmail, *, job_score: int) -> ClassificationResult:
    """
    Simple keyword classifier.

    Confidence is heuristic: fraction of matched outcome/invitation keywords.
    """

    text_l = ((email.subject or "") + "\n" + email.body_for_detection).lower()

    # Anchor: application submission/receipt confirmation.
    # These templates are common for “you submitted successfully; recruiter will contact you”.
    anchor_markers = [
        "successfully completed",
        "successfully submitted",
        "your application has been received",
        "we have received your application",
        "has been received",
        "thank you for applying",
        "thank you for your time and interest",
        "thank you for your time and interest in",
        "thank you for your time and interest in the",
        "thank you for your application",
        "you did it",
        "great job",
    ]

    matched_anchor = sum(1 for m in anchor_markers if m in text_l)

    # Job-context gating: avoid calling “rejected/offer/interview” if it’s not clearly about a candidate/job.
    job_context_markers = [
        "application",
        "candidate",
        "recruiter",
        "role",
        "position",
        "job",
        "we will contact you",
        "next steps",
        "your candidacy",
    ]
    job_context_hit = any(m in text_l for m in job_context_markers)

    rejected_markers = [
        # Direct markers
        "rejected",
        "declined",
        "not selected",
        "unfortunately",
        "regret to inform",
        # Common template variants
        "move forward with candidates",
        "move forward with candidates whose",
        "not to proceed",
        "chosen not to proceed",
        "will not be taking your application further",
        "will not be taking your application",
        "not be taking your application further",
        "not taking your application further",
        "not fully align",
        "more closely matches",
        "more closely match",
        "we've decided to move forward",
        "we have decided to move forward",
        "we decided to move forward",
        "we have chosen not to proceed",
        "we've chosen not to proceed",
        "will not proceed",
        # Your examples
        "thank you for your time and interest",
        "thank you for your interest",
        "application further",
    ]
    offer_markers = [
        "offer",
        "compensation",
        "salary",
        "employment",
        "congratulations",
        "we are pleased to",
    ]
    interview_markers = [
        "interview",
        "technical interview",
        "screen",
        "call",
        "zoom",
        "hr interview",
        "next steps",
    ]

    matched_rejected = sum(1 for m in rejected_markers if m in text_l)
    matched_offer = sum(1 for m in offer_markers if m in text_l)
    matched_interview = sum(1 for m in interview_markers if m in text_l)

    # Determine label by highest matched count.
    counts = {
        "application_received": matched_anchor,
        "rejected": matched_rejected,
        "offer": matched_offer,
        "interview": matched_interview,
    }

    best_label: Optional[str] = None
    best = 0
    for label, c in counts.items():
        if c > best:
            best = c
            best_label = label

    if best_label is None:
        return ClassificationResult(label="pending", confidence=0.1)

    # If we strongly detect the submission/receipt anchor, prefer it over outcomes.
    if best_label == "application_received":
        confidence = min(0.95, 0.5 + min(0.45, matched_anchor * 0.15) + min(0.1, job_score / 250))
        if confidence < settings.job_classifier_min_confidence:
            return ClassificationResult(label="pending", confidence=confidence)
        return ClassificationResult(label="application_received", confidence=confidence)

    # For outcomes, require job-context to reduce false positives.
    if not job_context_hit and best_label in ("rejected", "offer", "interview"):
        return ClassificationResult(label="pending", confidence=0.2)

    total_outcome = matched_rejected + matched_offer + matched_interview
    confidence = min(0.95, (best / max(1, total_outcome)) * 0.85 + min(0.15, job_score / 180))
    if confidence < settings.job_classifier_min_confidence and best_label in ("rejected", "offer", "interview"):
        return ClassificationResult(label="pending", confidence=confidence)

    return ClassificationResult(label=best_label, confidence=confidence)

