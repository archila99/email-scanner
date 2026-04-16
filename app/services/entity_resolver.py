from __future__ import annotations

import logging
import datetime as dt
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from sqlmodel import Session, select

from app.models import Emails, JobApplicationEntities, JobApplicationEntityEmails, JobApplications
from app.services.company_normalize import normalize_company_name
from app.services.company_role_extract import extract_company_role, parse_sender_domain

logger = logging.getLogger(__name__)


def _is_blank(s: str | None) -> bool:
    return s is None or str(s).strip() == ""


def _as_utc(dt_value: dt.datetime) -> dt.datetime:
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=dt.timezone.utc)
    return dt_value.astimezone(dt.timezone.utc)


def _as_naive_utc(dt_value: dt.datetime) -> dt.datetime:
    return _as_utc(dt_value).replace(tzinfo=None)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9]{3,}", (text or "").lower())
    return {w for w in words if w not in {"the", "and", "for", "your", "you", "our", "with", "from"}}


def _subject_similarity(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _domain_similarity(email_domain: Optional[str], entity_domain: Optional[str]) -> float:
    if not email_domain or not entity_domain:
        return 0.0
    e = email_domain.lower().strip()
    d = entity_domain.lower().strip()
    if e == d:
        return 1.0
    if e.endswith(d) or d.endswith(e):
        return 0.75
    # brand-ish similarity
    return SequenceMatcher(a=e.split(".", 1)[0], b=d.split(".", 1)[0]).ratio()


def _time_proximity_days(a: dt.datetime, b: dt.datetime) -> float:
    da = _as_utc(a)
    db = _as_utc(b)
    diff = abs((da - db).total_seconds()) / 86400.0
    return max(0.0, 1.0 - (diff / 30.0))


def _status_from_event(event_type: str) -> str:
    t = (event_type or "").lower()
    if t == "rejection":
        return "rejected"
    if t == "offer":
        return "offered"
    if t == "interview":
        return "interviewing"
    if t == "application":
        return "applied"
    return "unknown"


def _merge_pipeline_status(current: str, event_type: str) -> str:
    """
    Conservative pipeline merge:
    - terminal negative (rejected) sticks
    - positive terminal (offered) sticks unless contradicted by explicit rejection (rare)
    """
    cur = (current or "unknown").lower()
    nxt = _status_from_event(event_type)

    if cur == "rejected":
        return "rejected"
    if cur == "offered" and nxt != "rejected":
        return "offered"
    if nxt == "rejected":
        return "rejected"
    if nxt == "offered":
        return "offered"
    if nxt == "interviewing":
        return "interviewing"
    if nxt == "applied":
        return "applied" if cur == "unknown" else cur
    return cur if cur != "unknown" else nxt


@dataclass(frozen=True)
class ResolveResult:
    entity_id: int
    created: bool
    score: float


def resolve_job_application(
    session: Session,
    job_application: JobApplications,
    *,
    threshold: float = 60.0,
) -> Optional[ResolveResult]:
    """
    Attach a JobApplications event to a grouped JobApplicationEntities row.

    Safe-by-default: swallow errors (ingestion must not fail).
    """

    try:
        email = session.get(Emails, job_application.email_id)
        if not email:
            return None

        extract = extract_company_role(
            email,
            allow_llm_company=_is_blank(job_application.matched_company),
            allow_llm_role=_is_blank(job_application.matched_role),
        )
        company = (job_application.matched_company or extract.company or "").strip()
        company = normalize_company_name(company) if company else ""
        if not company:
            company = "Unknown Employer"

        role = (job_application.matched_role or extract.role or "").strip() or None
        role_norm = role.lower() if role else None

        email_domain = parse_sender_domain(email.sender)

        candidates = session.exec(select(JobApplicationEntities)).all()
        best: tuple[float, Optional[JobApplicationEntities]] = (-1.0, None)

        for ent in candidates:
            score = 0.0
            ent_company = normalize_company_name(ent.company_name)
            if ent_company.lower() == company.lower():
                score += 50.0

            if role_norm and ent.role and ent.role.strip().lower() == role_norm:
                score += 20.0

            score += 20.0 * _domain_similarity(email_domain, ent.company_domain)

            score += 20.0 * _subject_similarity(email.subject, ent.company_name)

            score += 10.0 * _time_proximity_days(email.received_at, ent.last_email_date)

            if score > best[0]:
                best = (score, ent)

        best_score, best_ent = best
        # Store naive UTC timestamps to match existing Emails/JobApplications rows.
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

        if best_ent is not None and best_score >= threshold:
            entity = best_ent
            created = False
            logger.info(
                "[ENTITY] attach job_application_id=%s email_id=%s entity_id=%s score=%.1f",
                job_application.id,
                email.id,
                entity.id,
                best_score,
            )
        else:
            entity = JobApplicationEntities(
                company_name=company,
                company_domain=email_domain,
                role=role,
                status=_status_from_event(job_application.type),
                email_count=0,
                confidence_score=float(extract.confidence) if extract.confidence else None,
                created_by=("llm" if (extract.company_method == "llm" or extract.role_method == "llm") else "rule_based"),
                last_event_type=job_application.type,
                first_email_date=_as_naive_utc(email.received_at),
                last_email_date=_as_naive_utc(email.received_at),
                created_at=now,
                last_updated_at=now,
            )
            session.add(entity)
            session.commit()
            session.refresh(entity)
            created = True
            best_score = max(best_score, 0.0)
            logger.info(
                "[ENTITY] create job_application_id=%s email_id=%s entity_id=%s score=%.1f company_method=%s role_method=%s",
                job_application.id,
                email.id,
                entity.id,
                best_score,
                extract.company_method,
                extract.role_method,
            )

        # Link email to entity (idempotent)
        link = session.exec(
            select(JobApplicationEntityEmails)
            .where(JobApplicationEntityEmails.entity_id == entity.id)
            .where(JobApplicationEntityEmails.email_id == email.id)
        ).first()
        if not link:
            session.add(JobApplicationEntityEmails(entity_id=entity.id, email_id=email.id))  # type: ignore[arg-type]
            entity.email_count = int(entity.email_count or 0) + 1

        # Update entity stats
        entity.last_event_type = job_application.type
        entity.last_email_date = _as_naive_utc(
            max(_as_utc(entity.last_email_date), _as_utc(email.received_at))
        )
        entity.first_email_date = _as_naive_utc(
            min(_as_utc(entity.first_email_date), _as_utc(email.received_at))
        )
        entity.status = _merge_pipeline_status(entity.status, job_application.type)
        entity.last_updated_at = now

        # Prefer stronger confidence if we learn more over time
        if extract.confidence and (entity.confidence_score is None or extract.confidence > float(entity.confidence_score)):
            entity.confidence_score = float(extract.confidence)

        if not entity.company_domain and email_domain:
            entity.company_domain = email_domain

        if not entity.role and role:
            entity.role = role

        session.add(entity)
        session.commit()

        return ResolveResult(entity_id=entity.id, created=created, score=float(best_score))
    except Exception:
        logger.exception("[ENTITY] resolve failed job_application_id=%s", getattr(job_application, "id", None))
        return None


def resolve_job_application_nonblocking(session: Session, job_application: JobApplications) -> None:
    # Kept as a separate function for clarity at call sites.
    resolve_job_application(session, job_application)
