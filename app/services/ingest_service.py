from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.classifiers.keyword_classifier import classify_job_outcome
from app.classifiers.ollama_classifier import classify_with_ollama
from app.config import settings
from app.detector.hard_blocks import is_hard_blocked
from app.email.gmail_provider import GmailProvider
from app.email.preprocess import preprocess_email
from app.models import IngestedEmail, TrackedApplication
from app.tracker.application_tracker import match_application, update_application_status_from_email


def ingest_new_emails_once(
    session: Session,
    provider: GmailProvider,
    *,
    query: str,
    max_results: int,
) -> dict[str, Any]:
    """
    Poll Gmail once using `query`, ingest unseen messages, and update application statuses.
    """

    message_ids = provider.list_message_ids(query=query, max_results=max_results)
    processed: list[str] = []
    ingested_count = 0
    classified_count = 0

    if not message_ids:
        return {
            "processed_message_ids": processed,
            "ingested_count": ingested_count,
            "classified_count": classified_count,
        }

    for message_id in message_ids:
        exists = session.exec(
            select(IngestedEmail).where(IngestedEmail.provider_message_id == message_id)
        ).first()
        if exists:
            continue

        raw = provider.get_message(message_id)
        normalized = preprocess_email(raw)

        # Thread context: if we've already linked any message in this Gmail thread to a tracked job,
        # we can reuse it for follow-ups that don't repeat all keywords.
        thread_matched_application_id = None
        if raw.thread_id:
            thread_matched_application_id = session.exec(
                select(IngestedEmail.matched_application_id).where(
                    (IngestedEmail.thread_id == raw.thread_id)
                    & (IngestedEmail.matched_application_id.isnot(None))
                )
            ).first()

        classification_label: str | None = None
        classification_conf: float | None = None
        matched_application_id = thread_matched_application_id
        extracted_company: str | None = None
        extracted_role: str | None = None
        extraction_source: str | None = None

        # New approach:
        # - Hard-block obvious noise
        # - Use LLM as primary classifier/extractor
        # - Use keyword classifier only as fallback (LLM disabled/unavailable)
        if not is_hard_blocked(normalized):
            if settings.use_llm:
                try:
                    llm = classify_with_ollama(normalized)
                    extraction_source = "ollama"
                    extracted_company = llm.company
                    extracted_role = llm.role
                    if llm.is_job_related:
                        classification_label = (
                            llm.category if llm.category not in ("not_job_related", "other_job_related") else None
                        )
                        classification_conf = llm.confidence
                        if classification_label is not None:
                            classified_count += 1
                except Exception:
                    # Fall back to keyword classifier if Ollama is unavailable or returns invalid JSON.
                    pass

            if not settings.use_llm or (settings.use_llm and extraction_source is None):
                classified = classify_job_outcome(normalized, job_score=0)
                if classified.label != "pending":
                    classification_label = classified.label
                    classification_conf = classified.confidence
                    extraction_source = extraction_source or "keyword"
                    classified_count += 1

            # Anchor: create a tracked job when we see a “your application has been received” template.
            if classification_label == "application_received" and matched_application_id is None:
                # Prefer LLM extraction if present.
                company = extracted_company or (normalized.from_domain.split(".", 1)[0] if normalized.from_domain else None)
                role = extracted_role or "Unknown Role"

                tracked = TrackedApplication(
                    company=company,
                    role=role,
                    company_domain=normalized.from_domain,
                    resume_version_used=None,
                    status="pending",
                    last_response_at=normalized.received_at,
                )
                session.add(tracked)
                session.commit()
                session.refresh(tracked)
                matched_application_id = tracked.id

            # Outcome linking:
            # - Prefer thread match if it exists
            # - Otherwise (or if it looks weak), fall back to domain+role matching
            if classification_label in ("rejected", "interview", "offer"):
                candidate = match_application(
                    session,
                    from_domain=normalized.from_domain,
                    subject=normalized.subject,
                    body_text=normalized.body_for_detection,
                )
                if candidate and (matched_application_id is None or matched_application_id != candidate.application_id):
                    matched_application_id = candidate.application_id

        email_row = IngestedEmail(
            provider_message_id=message_id,
            thread_id=raw.thread_id,
            from_address=normalized.from_address,
            from_domain=normalized.from_domain,
            subject=normalized.subject,
            body_excerpt=normalized.body_excerpt,
            received_at=normalized.received_at,
            job_score=None,
            detector_version="ollama-llm-v1" if extraction_source == "ollama" else "keyword-detector-v1",
            classification=classification_label,
            classifier_confidence=classification_conf,
            extracted_company=extracted_company,
            extracted_role=extracted_role,
            extraction_source=extraction_source,
            matched_application_id=matched_application_id,
        )
        session.add(email_row)
        session.flush()  # Ensure the row is part of the session.

        if matched_application_id is not None and classification_label in ("rejected", "interview", "offer"):
            app = session.get(TrackedApplication, matched_application_id)
            if app is not None:
                update_application_status_from_email(
                    session,
                    application=app,
                    ingested_email=email_row,
                    new_status=classification_label,
                    confidence=float(classification_conf or 0.0),
                )

        session.commit()

        ingested_count += 1
        processed.append(message_id)

        # Backfill linking/status for messages processed before the anchor in their thread.
    # This makes the anchor+thread approach robust to Gmail returning newest messages first.
    if processed:
        emails_to_fix = session.exec(
            select(IngestedEmail).where(IngestedEmail.provider_message_id.in_(processed))
        ).all()
        outcome_labels = ("rejected", "interview", "offer")

        for email_row in emails_to_fix:
            if email_row.matched_application_id is not None:
                continue
            if not email_row.thread_id:
                continue

            thread_matched_id = session.exec(
                select(IngestedEmail.matched_application_id).where(
                    (IngestedEmail.thread_id == email_row.thread_id)
                    & (IngestedEmail.matched_application_id.isnot(None))
                )
            ).first()

            if thread_matched_id is not None:
                email_row.matched_application_id = thread_matched_id
            elif email_row.classification in outcome_labels:
                # If this is an outcome email but the thread didn't help, try domain+role matching
                # after the anchor was created.
                candidate = match_application(
                    session,
                    from_domain=email_row.from_domain,
                    subject=email_row.subject,
                    body_text=email_row.body_excerpt or "",
                )
                if candidate:
                    email_row.matched_application_id = candidate.application_id

            if email_row.matched_application_id is None:
                continue

            if email_row.classification in outcome_labels and thread_matched_id is not None:
                app = session.get(TrackedApplication, thread_matched_id)
                if app is not None and email_row.classification is not None:
                    update_application_status_from_email(
                        session,
                        application=app,
                        ingested_email=email_row,
                        new_status=email_row.classification,
                        confidence=float(email_row.classifier_confidence or 0.0),
                    )

        session.commit()

    return {
        "processed_message_ids": processed,
        "ingested_count": ingested_count,
        "classified_count": classified_count,
    }

