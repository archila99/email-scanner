from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.models import Emails, JobApplicationEntities, Reminders


def get_dashboard_summary(*, session: Session) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()

    emails_today = session.exec(
        select(Emails).where(Emails.received_at >= dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc))
    ).all()

    active_entities = session.exec(
        select(JobApplicationEntities).where(JobApplicationEntities.status.in_(["applied", "interviewing"]))
    ).all()

    followups_due = session.exec(
        select(Reminders).where(Reminders.type == "followup").where(Reminders.status == "pending")
    ).all()

    interviews = session.exec(select(JobApplicationEntities).where(JobApplicationEntities.status == "interviewing")).all()

    return {
        "generated_at": now,
        "new_emails_today": len(emails_today),
        "active_applications": len(active_entities),
        "followups_pending": len(followups_due),
        "interviewing": len(interviews),
    }

