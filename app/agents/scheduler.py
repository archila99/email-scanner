from __future__ import annotations

"""
Sequential scheduler entrypoint.

This is designed to be invoked by cron/launchd (recommended) so we avoid
introducing in-process background concurrency.
"""

import datetime as dt
import logging
from pathlib import Path

from sqlmodel import Session

from app.agents.followup_agent import run_followup_agent
from app.agents.summary_agent import get_dashboard_summary
from app.agents.sync_agent import run_sync_agent
from app.email.gmail_auth import build_gmail_service
from app.email.gmail_provider import GmailProvider
from app.services.execution_guard import FileLock

logger = logging.getLogger(__name__)


def run_daily_sequential(*, session: Session) -> dict:
    """
    Runs: sync -> followup -> summary, sequentially.
    """
    started = dt.datetime.now(dt.timezone.utc)

    lock = FileLock(path=Path("/tmp/gmail_scanner_agents.lock"))
    if not lock.acquire(blocking=False):
        finished = dt.datetime.now(dt.timezone.utc)
        logger.warning("[AGENT] daily run skipped: busy")
        return {"started_at": started, "finished_at": finished, "skipped": True, "reason": "agents_busy"}

    try:
        service = build_gmail_service()
        provider = GmailProvider(service)

        sync_res = run_sync_agent(session=session, provider=provider)
        follow_res = run_followup_agent(session=session)
        summary = get_dashboard_summary(session=session)

        finished = dt.datetime.now(dt.timezone.utc)
        logger.info("[AGENT] daily run finished")

        return {
            "started_at": started,
            "finished_at": finished,
            "sync": sync_res,
            "followup": follow_res,
            "summary": summary,
        }
    finally:
        lock.release()

