from __future__ import annotations

import datetime as dt
import logging

from sqlmodel import Session

from app.agents.base import AgentResult
from app.config import settings
from app.email.gmail_provider import GmailProvider
from app.services.execution_guard import ingestion_lock
from app.services.ingest import ingest_new_emails_once

logger = logging.getLogger(__name__)


def run_sync_agent(*, session: Session, provider: GmailProvider) -> AgentResult:
    started = dt.datetime.now(dt.timezone.utc)
    lock = ingestion_lock()
    if not lock.acquire(blocking=False):
        finished = dt.datetime.now(dt.timezone.utc)
        return AgentResult(
            ok=True,
            agent="sync_agent",
            started_at=started,
            finished_at=finished,
            details={"skipped": True, "reason": "ingestion_busy"},
        )

    try:
        res = ingest_new_emails_once(
            session,
            provider,
            query=settings.gmail_search_query,
            max_results=settings.gmail_max_results_per_poll,
        )
        finished = dt.datetime.now(dt.timezone.utc)
        logger.info("[AGENT] sync_agent ok ingested=%s classified=%s", res.get("ingested_count"), res.get("classified_count"))
        return AgentResult(ok=True, agent="sync_agent", started_at=started, finished_at=finished, details=res)
    except Exception as e:
        logger.exception("[AGENT] sync_agent failed")
        finished = dt.datetime.now(dt.timezone.utc)
        return AgentResult(ok=False, agent="sync_agent", started_at=started, finished_at=finished, details={}, error=str(e))
    finally:
        lock.release()

