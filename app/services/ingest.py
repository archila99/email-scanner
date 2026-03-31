from __future__ import annotations

import logging
import datetime as dt
from typing import Any, Optional

from sqlmodel import Session, select

from app.classifiers.body_classifier import classify_from_body
from app.classifiers.ollama_classifier import classify_with_ollama
from app.classifiers.subject_classifier import classify_from_subject
from app.email.gmail_provider import GmailProvider
from app.email.preprocess import preprocess_email
from app.models import Emails, JobApplications

logger = logging.getLogger(__name__)


def _parse_company_role_from_subject(subject: str) -> tuple[Optional[str], Optional[str]]:
    # Minimal heuristic; safe to improve later.
    s = (subject or "").strip()
    if not s:
        return None, None
    # e.g. "Thank you for your application to UiPath: Software Engineer Intern"
    if " to " in s:
        after = s.split(" to ", 1)[1]
        company = after.split(":", 1)[0].strip() if ":" in after else after.strip()
        role = after.split(":", 1)[1].strip() if ":" in after else None
        return (company or None), (role or None)
    return None, None


def _is_recommendation_or_job_alert(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    return any(
        phrase in text
        for phrase in (
            "our recommendation",
            "recommended jobs",
            "jobs you may like",
            "job alert",
            "career-ready",
            "opportunities waiting for you",
            "saved job search",
            "new jobs posted",
        )
    )


def ingest_new_emails_once(
    session: Session,
    provider: GmailProvider,
    *,
    query: str,
    max_results: int,
    subject_confidence_threshold: float = 0.85,
) -> dict[str, Any]:
    message_ids = provider.list_message_ids(query=query, max_results=max_results)
    processed: list[str] = []

    if not message_ids:
        return {"processed_message_ids": processed, "ingested_count": 0, "classified_count": 0}

    ingested_count = 0
    classified_count = 0

    for message_id in message_ids:
        # Prevent duplicate import (raw Gmail id is stable).
        exists = session.exec(select(Emails).where(Emails.raw_data == message_id)).first()
        if exists:
            continue

        raw = provider.get_message(message_id)
        normalized = preprocess_email(raw)

        email_row = Emails(
            subject=normalized.subject or "",
            body=normalized.body_clean or None,
            sender=normalized.from_address or (normalized.from_domain or "unknown"),
            received_at=normalized.received_at or dt.datetime.now(dt.timezone.utc),
            raw_data=message_id,
            classification=None,
        )
        recommendation_noise = _is_recommendation_or_job_alert(email_row.subject, email_row.body or "")

        subj = classify_from_subject(email_row.subject)
        if recommendation_noise:
            session.add(email_row)
            session.commit()
            session.refresh(email_row)
            logger.info(f"[TRACKING] created=False email_id={email_row.id} recommendation_noise=True")
        elif subj.type and subj.confidence >= subject_confidence_threshold:
            email_row.classification = subj.type
            session.add(email_row)
            session.commit()
            session.refresh(email_row)

            company, role = _parse_company_role_from_subject(email_row.subject)
            session.add(
                JobApplications(
                    email_id=email_row.id,  # type: ignore[arg-type]
                    type=subj.type,
                    matched_company=company,
                    matched_role=role,
                )
            )
            session.commit()
            classified_count += 1

            logger.info(f"[SUBJECT HIT] {email_row.subject} -> {subj.type} ({subj.confidence:.2f})")
            logger.info(f"[TRACKING] created JobApplications for email_id={email_row.id}")
        else:
            session.add(email_row)
            session.commit()
            session.refresh(email_row)

            body_hit = classify_from_body(email_row.body or "")
            if body_hit.type and body_hit.confidence >= 0.9:
                t = body_hit.type
                company, role = _parse_company_role_from_subject(email_row.subject)
                email_row.classification = t  # type: ignore[assignment]
                session.add(email_row)
                session.commit()

                session.add(
                    JobApplications(
                        email_id=email_row.id,  # type: ignore[arg-type]
                        type=t,  # type: ignore[arg-type]
                        matched_company=company,
                        matched_role=role,
                    )
                )
                session.commit()
                classified_count += 1
                logger.info(f"[BODY HIT] {email_row.subject} -> {t} ({body_hit.confidence:.2f})")
                logger.info(f"[TRACKING] created JobApplications for email_id={email_row.id}")
            else:
                llm = classify_with_ollama(normalized)
                # Keep only job-related types; ignore other/not_job_related for now.
                t = llm.type if llm.type in ("application", "rejection", "interview", "offer") else None

                if t:
                    email_row.classification = t  # type: ignore[assignment]
                    session.add(email_row)
                    session.commit()

                    session.add(
                        JobApplications(
                            email_id=email_row.id,  # type: ignore[arg-type]
                            type=t,  # type: ignore[arg-type]
                            matched_company=llm.company,
                            matched_role=llm.role,
                        )
                    )
                    session.commit()
                    classified_count += 1

                logger.info(f"[LLM USED] {email_row.subject} -> {t or 'not_job_related'} ({llm.confidence:.2f})")
                logger.info(f"[TRACKING] created={bool(t)} email_id={email_row.id}")

        ingested_count += 1
        processed.append(message_id)

    return {"processed_message_ids": processed, "ingested_count": ingested_count, "classified_count": classified_count}
