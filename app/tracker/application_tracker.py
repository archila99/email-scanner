from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import re
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models import ApplicationEvent, IngestedEmail, TrackedApplication
APP_STATUS_PENDING = "pending"
APP_STATUS_REJECTED = "rejected"
APP_STATUS_INTERVIEW = "interview"
APP_STATUS_OFFER = "offer"


@dataclass(frozen=True)
class ApplicationMatch:
    application_id: int
    score: int


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _extract_company_role(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Best-effort extraction from typical rejection/confirmation templates.
    Returns (role, company).
    """

    t = text or ""

    # Examples:
    # - "role at Anaplan"
    # - "position of Sales Advisor"
    # - "your application for the Junior Software Engineer role at Anaplan"
    patterns = [
        # "... role at Company"
        r"(?P<role>.+?) role at (?P<company>.+?)(?:[\\.|\\n|\\r|$])",
        # "position of X at Y"
        r"position of (?P<role>.+?)(?:\\s+at\\s+(?P<company>.+?))?(?:[\\.|\\n|\\r|$])",
        # "application for ... role at Company"
        r"application (?:for|to) (?:an?|the)?\\s*(?P<role>.+?)(?:\\s+at\\s+(?P<company>.+?))?(?:[\\.|\\n|\\r|$])",
        # "Thank you for your application to ... role at Company"
        r"application (?:to|for) (?P<role>.+?)(?:\\s+at\\s+(?P<company>.+?))?(?:[\\.|\\n|\\r|$])",
        # "... role at Company"
        r"your (?:application|candidacy)[\\s\\S]{0,80}?(?P<role>.+?) (?:at|role at) (?P<company>.+?)(?:[\\.|\\n|\\r|$])",
    ]

    for pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            role = m.groupdict().get("role")
            company = m.groupdict().get("company")
            role = role.strip() if role else None
            company = company.strip() if company else None
            if role:
                role = re.sub(r"[^A-Za-z0-9\\-\\+&/\\s]", "", role)
                role = re.sub(r"\\s{2,}", " ", role).strip()
            if company:
                company = re.sub(r"[^A-Za-z0-9\\-\\+&/\\s]", "", company)
                company = re.sub(r"\\s{2,}", " ", company).strip()
            if role or company:
                return role, company
    return None, None


def match_application(
    session: Session,
    *,
    from_domain: Optional[str],
    subject: Optional[str],
    body_text: str,
) -> Optional[ApplicationMatch]:
    apps = session.exec(select(TrackedApplication)).all()
    if not apps:
        return None

    subject_l = _norm(subject)
    body_l = _norm(body_text)
    from_domain_l = _norm(from_domain)

    extracted_role, extracted_company = _extract_company_role(body_text)
    extracted_role_l = _norm(extracted_role)
    extracted_company_l = _norm(extracted_company)

    best: Optional[ApplicationMatch] = None
    for app in apps:
        score = 0
        company_l = _norm(app.company)
        role_l = _norm(app.role)
        company_domain_l = _norm(app.company_domain)

        # Strongest signals first: domain match.
        if company_domain_l and from_domain_l:
            if from_domain_l == company_domain_l or from_domain_l.endswith(company_domain_l):
                score += 35

        # Next: explicit extracted company/role match (even if domain differs).
        if extracted_company_l and company_l and (extracted_company_l in company_l or company_l in extracted_company_l):
            score += 15
        if extracted_role_l and role_l:
            # Token overlap is more robust than substring.
            app_tokens = set(role_l.split())
            extracted_tokens = set(extracted_role_l.split())
            overlap = len(app_tokens & extracted_tokens)
            if overlap:
                score += 10 + min(10, overlap * 2)

        # Fallback: substring match in subject/body.
        if company_l and (company_l in subject_l or company_l in body_l):
            score += 10
        if role_l and (role_l in subject_l or role_l in body_l):
            score += 6

        if best is None or score > best.score:
            best = ApplicationMatch(application_id=app.id, score=score)  # type: ignore[arg-type]

    # Threshold: require some evidence.
    if best and best.score >= 10:
        return best
    return None


def update_application_status_from_email(
    session: Session,
    *,
    application: TrackedApplication,
    ingested_email: IngestedEmail,
    new_status: str,
    confidence: float,
) -> None:
    if application.id is None:
        raise ValueError("TrackedApplication must be persisted (id must not be None).")

    from_status = application.status
    application.last_response_at = ingested_email.received_at or dt.datetime.utcnow()

    # Prevent status regressions for MVP stability.
    if new_status not in {APP_STATUS_PENDING, APP_STATUS_REJECTED, APP_STATUS_INTERVIEW, APP_STATUS_OFFER}:
        new_status = APP_STATUS_PENDING

    # Keep `pending` from undoing a known outcome.
    if new_status == APP_STATUS_PENDING:
        application.updated_at = dt.datetime.utcnow()
        return

    if from_status == APP_STATUS_REJECTED:
        return

    if from_status == APP_STATUS_OFFER and new_status != APP_STATUS_REJECTED:
        return

    if from_status == APP_STATUS_INTERVIEW and new_status not in {APP_STATUS_OFFER, APP_STATUS_REJECTED}:
        return

    # pending -> (interview/offer/rejected) is allowed
    if from_status == APP_STATUS_PENDING:
        application.status = new_status
        application.updated_at = dt.datetime.utcnow()
        if from_status != application.status:
            session.add(
                ApplicationEvent(
                    application_id=application.id,
                    event_type="status_changed",
                    from_status=from_status,
                    to_status=application.status,
                )
            )
        return

    # For completeness: handle other allowed transitions explicitly.
    if new_status != from_status:
        application.status = new_status
        application.updated_at = dt.datetime.utcnow()
        session.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="status_changed",
                from_status=from_status,
                to_status=application.status,
            )
        )

