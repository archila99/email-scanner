from __future__ import annotations

import logging
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.models import Emails, JobApplicationEntities, JobApplicationEntityEmails, JobApplications, Reminders
from app.schemas import (
    AgentResultRead,
    DashboardSummary,
    EmailRead,
    IngestRunResponse,
    JobApplicationEntityEmailRead,
    JobApplicationEntityRead,
    JobApplicationRead,
    ReminderRead,
)
from app.services.ingest import ingest_new_emails_once
from app.services.execution_guard import ingestion_lock
from app.agents.followup_agent import run_followup_agent
from app.agents.summary_agent import get_dashboard_summary
from app.agents.sync_agent import run_sync_agent

from .deps import get_db, get_gmail_provider


router = APIRouter()
logger = logging.getLogger(__name__)


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

    lock = ingestion_lock()
    if not lock.acquire(blocking=False):
        logger.warning("[INGEST] busy: another ingestion is running")
        return {"processed_message_ids": [], "ingested_count": 0, "classified_count": 0}

    try:
        res = ingest_new_emails_once(
            session,
            provider,
            query=settings.gmail_search_query,
            max_results=settings.gmail_max_results_per_poll,
        )
        return res
    finally:
        lock.release()


@router.get("/agents/status")
def agents_status() -> dict[str, bool]:
    lock = ingestion_lock()
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
    return {"ingest_busy": not acquired}


@router.post("/agents/sync/run", response_model=AgentResultRead)
def agents_sync_run(
    session: Session = Depends(get_db),
    provider=Depends(get_gmail_provider),
) -> dict:
    res = run_sync_agent(session=session, provider=provider)
    return res.__dict__


@router.post("/agents/followup/run", response_model=AgentResultRead)
def agents_followup_run(session: Session = Depends(get_db)) -> dict:
    res = run_followup_agent(session=session)
    return res.__dict__


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(session: Session = Depends(get_db)) -> dict:
    return get_dashboard_summary(session=session)


@router.get("/reminders", response_model=list[ReminderRead])
def list_reminders(session: Session = Depends(get_db)) -> list[Reminders]:
    return session.exec(select(Reminders).order_by(Reminders.created_at.desc())).all()

