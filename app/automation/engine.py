from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from app.config import settings
from app.models import ApplicationEvent, TrackedApplication

APP_STATUS_PENDING = "pending"


def generate_followup_due_actions(session: Session) -> int:
    """
    Create `followup_due` events for pending applications that haven't had a response.

    MVP behavior:
    - Uses `TrackedApplication.last_response_at` to measure “no response”
    - Ensures we don't spam by checking if a followup_due was created recently.
    """

    now = dt.datetime.utcnow()
    cutoff = now - dt.timedelta(days=settings.followup_after_days_no_response)

    pending_apps = session.exec(
        select(TrackedApplication).where(TrackedApplication.status == APP_STATUS_PENDING)
    ).all()

    created = 0
    for app in pending_apps:
        last = app.last_response_at
        if last is not None and last > cutoff:
            continue

        # Avoid duplicates: if we already created a followup_due within the last day, skip.
        if app.id is None:
            continue

        existing = session.exec(
            select(ApplicationEvent).where(
                (ApplicationEvent.application_id == app.id)
                & (ApplicationEvent.event_type == "followup_due")
            )
        ).all()
        if any((e.occurred_at or now) > (now - dt.timedelta(days=1)) for e in existing):
            continue

        session.add(
            ApplicationEvent(
                application_id=app.id,
                event_type="followup_due",
                payload_json=f'{{"days_no_response": {settings.followup_after_days_no_response}}}',
            )
        )
        created += 1

    session.commit()
    return created

