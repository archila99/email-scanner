from __future__ import annotations

import datetime as dt
import logging

from sqlmodel import Session, select

from app.agents.base import AgentResult
from app.models import JobApplicationEntities, JobApplicationEntityEmails, JobApplications, Reminders

logger = logging.getLogger(__name__)


def _is_business_day(d: dt.date) -> bool:
    return d.weekday() < 5


def _business_days_between(start: dt.date, end: dt.date) -> int:
    if end < start:
        start, end = end, start
    days = 0
    cur = start
    while cur < end:
        if _is_business_day(cur):
            days += 1
        cur += dt.timedelta(days=1)
    return days


def generate_followup_email(
    *,
    company_name: str,
    job_role: str | None,
    applied_at: dt.datetime | None,
) -> str:
    """
    Deterministic follow-up email draft stored in Reminders.generated_text.

    STRICT INPUT CONTRACT:
    - company_name (from JobApplicationEntities)
    - job_role (matched_role from JobApplicationEntities)
    - applied_at (timestamp of first application event from JobApplications via entity relation)
    """
    matched_role = (job_role or "").strip() or "the position"
    company = (company_name or "").strip() or "the company"

    current_date = dt.datetime.now(dt.timezone.utc).date()

    if applied_at is None:
        applied_time_sentence = "I applied approximately a few weeks ago"
    else:
        applied_date = applied_at.date()
        delta_days = (current_date - applied_date).days
        applied_weeks = max(0, int(round(delta_days / 7.0)))
        applied_time_sentence = f"I applied approximately {applied_weeks} weeks ago"

    subject = f"Following up on my application for {matched_role} at {company}"

    # Strict output string structure.
    return (
        f"Subject: {subject}\n\n"
        "Dear Hiring Team,\n\n"
        "I hope you're doing well.\n\n"
        f"I wanted to follow up on my application for {matched_role} at {company}.\n\n"
        f"{applied_time_sentence}.\n\n"
        "I remain very interested in the opportunity and would appreciate any updates regarding the status of my application.\n\n"
        "Thank you for your time and consideration.\n\n"
        "Best regards,\n"
        "[Your Name]\n"
    )


def _get_first_application_at(session: Session, entity_id: int) -> dt.datetime | None:
    """
    Derive applied_at for an entity:
    - Look at linked emails for this entity (JobApplicationEntityEmails)
    - Consider JobApplications rows of type 'application'
    - Pick the earliest created_at (first application event)
    """
    email_ids = session.exec(
        select(JobApplicationEntityEmails.email_id).where(JobApplicationEntityEmails.entity_id == entity_id)
    ).all()
    if not email_ids:
        return None

    first_applied = session.exec(
        select(JobApplications.created_at)
        .where(JobApplications.email_id.in_(email_ids))
        .where(JobApplications.type == "application")
        .order_by(JobApplications.created_at.asc())
        .limit(1)
    ).first()
    return first_applied


def run_followup_agent(*, session: Session, business_days_threshold: int = 8) -> AgentResult:
    started = dt.datetime.now(dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)

    # Ensure all pending follow-up reminders always have strict draft format.
    strict_prefix = "Subject: Following up on my application for "
    pending = session.exec(
        select(Reminders)
        .where(Reminders.type == "followup")
        .where(Reminders.status == "pending")
    ).all()
    drafts_backfilled = 0
    for rem in pending:
        ent = session.get(JobApplicationEntities, rem.entity_id)
        if not ent:
            continue
        applied_at = _get_first_application_at(session, ent.id)
        rem.generated_text = generate_followup_email(
            company_name=ent.company_name,
            job_role=ent.role,
            applied_at=applied_at,
        )
        session.add(rem)
        session.commit()
        drafts_backfilled += 1

    entities = session.exec(
        select(JobApplicationEntities).where(JobApplicationEntities.status.in_(["applied", "interviewing"]))
    ).all()

    created = 0
    scanned = 0
    due = 0

    for ent in entities:
        scanned += 1
        last = ent.last_email_date
        # last_email_date is stored naive in DB; treat as UTC.
        if last.tzinfo is None:
            last_dt = last.replace(tzinfo=dt.timezone.utc)
        else:
            last_dt = last.astimezone(dt.timezone.utc)

        bd = _business_days_between(last_dt.date(), now.date())
        if bd <= business_days_threshold:
            continue
        due += 1

        existing = session.exec(
            select(Reminders)
            .where(Reminders.entity_id == ent.id)
            .where(Reminders.type == "followup")
            .where(Reminders.status == "pending")
        ).first()
        if existing:
            # Enhancement (safe): if existing pending reminder has no draft yet OR
            # if it doesn't match our strict template format, regenerate it.
            existing_text = (existing.generated_text or "").strip()
            needs_update = not existing_text or not existing_text.startswith(
                "Subject: Following up on my application for "
            )
            if needs_update:
                applied_at = _get_first_application_at(session, ent.id)
                existing.generated_text = generate_followup_email(
                    company_name=ent.company_name,
                    job_role=ent.role,
                    applied_at=applied_at,
                )
                session.add(existing)
                session.commit()
            continue

        r = Reminders(
            entity_id=ent.id,  # type: ignore[arg-type]
            type="followup",
            due_date=now.replace(tzinfo=None),
            status="pending",
            generated_text=generate_followup_email(
                company_name=ent.company_name,
                job_role=ent.role,
                applied_at=_get_first_application_at(session, ent.id),
            ),
        )
        session.add(r)
        session.commit()
        created += 1

    finished = dt.datetime.now(dt.timezone.utc)
    logger.info("[AGENT] followup_agent ok scanned=%s due=%s created=%s", scanned, due, created)
    return AgentResult(
        ok=True,
        agent="followup_agent",
        started_at=started,
        finished_at=finished,
        details={
            "scanned_entities": scanned,
            "due_entities": due,
            "reminders_created": created,
            "drafts_backfilled": drafts_backfilled,
        },
    )

