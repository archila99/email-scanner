from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.models import Emails, JobApplicationEntities, JobApplicationEntityEmails, JobApplications
from app.schemas import (
    EmailRead,
    IngestRunResponse,
    JobApplicationEntityEmailRead,
    JobApplicationEntityRead,
    JobApplicationRead,
)
from app.services.ingest import ingest_new_emails_once

from .deps import get_db, get_gmail_provider


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/emails", response_model=list[EmailRead])
def list_emails(session: Session = Depends(get_db)) -> list[Emails]:
    return session.exec(select(Emails).order_by(Emails.received_at.desc())).all()


@router.get("/job-applications", response_model=list[JobApplicationRead])
def list_job_applications(session: Session = Depends(get_db)) -> list[JobApplications]:
    return session.exec(select(JobApplications).order_by(JobApplications.created_at.desc())).all()


@router.get("/job-application-entities", response_model=list[JobApplicationEntityRead])
def list_job_application_entities(session: Session = Depends(get_db)) -> list[JobApplicationEntities]:
    return session.exec(select(JobApplicationEntities).order_by(JobApplicationEntities.last_updated_at.desc())).all()


@router.get("/job-application-entity-emails", response_model=list[JobApplicationEntityEmailRead])
def list_job_application_entity_emails(session: Session = Depends(get_db)) -> list[JobApplicationEntityEmails]:
    return session.exec(select(JobApplicationEntityEmails)).all()


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

