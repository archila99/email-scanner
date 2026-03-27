from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.automation.engine import generate_followup_due_actions
from app.models import ApplicationEvent, TrackedApplication
from app.schemas import (
    ApplicationEventRead,
    IngestRunResponse,
    TrackedApplicationCreate,
    TrackedApplicationRead,
)
from app.services.ingest_service import ingest_new_emails_once

from .deps import get_db, get_gmail_provider


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/applications", response_model=TrackedApplicationRead)
def create_application(
    payload: TrackedApplicationCreate,
    session: Session = Depends(get_db),
) -> TrackedApplication:
    app = TrackedApplication(
        company=payload.company,
        role=payload.role,
        company_domain=payload.company_domain,
        resume_version_used=payload.resume_version_used,
    )
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


@router.get("/applications", response_model=list[TrackedApplicationRead])
def list_applications(session: Session = Depends(get_db)) -> list[TrackedApplication]:
    return session.exec(select(TrackedApplication)).all()


@router.post("/ingest/run", response_model=IngestRunResponse)
def ingest_run(
    session: Session = Depends(get_db),
    provider=Depends(get_gmail_provider),
) -> dict:
    from app.config import settings

    res = ingest_new_emails_once(
        session,
        provider,
        query=settings.gmail_search_query,
        max_results=settings.gmail_max_results_per_poll,
    )
    return res


@router.get("/automation/actions", response_model=list[ApplicationEventRead])
def automation_actions(session: Session = Depends(get_db)) -> list[ApplicationEvent]:
    # Generate events for follow-ups due; return newly created + existing followup_due events.
    generate_followup_due_actions(session)
    return session.exec(
        select(ApplicationEvent).where(ApplicationEvent.event_type == "followup_due").order_by(ApplicationEvent.occurred_at.desc())
    ).all()

