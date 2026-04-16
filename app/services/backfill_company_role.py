from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session, select, or_

from app.db import engine
from app.models import Emails, JobApplications
from app.services.company_role_extract import extract_company_role, needs_fill


logger = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    scanned: int = 0
    updated_rows: int = 0
    filled_company: int = 0
    filled_role: int = 0
    resolved_company_count: int = 0
    resolved_role_count: int = 0
    llm_usage_count: int = 0

    resolved_company_domain: int = 0
    resolved_company_subject: int = 0
    resolved_company_body: int = 0
    resolved_company_llm: int = 0
    unresolved_company: int = 0

    resolved_role_heuristic: int = 0
    unresolved_role: int = 0
    still_unresolved: int = 0


def _is_blank(s: str | None) -> bool:
    return s is None or str(s).strip() == ""


def backfill_job_application_company_role(session: Session) -> BackfillStats:
    stats = BackfillStats()

    stmt = select(JobApplications).where(
        or_(
            JobApplications.matched_company.is_(None),
            JobApplications.matched_company == "",
            JobApplications.matched_role.is_(None),
            JobApplications.matched_role == "",
        )
    )

    rows = session.exec(stmt).all()
    stats.scanned = len(rows)

    for ja in rows:
        email = session.get(Emails, ja.email_id)
        if not email:
            stats.unresolved_company += int(_is_blank(ja.matched_company))
            stats.unresolved_role += int(_is_blank(ja.matched_role))
            if _is_blank(ja.matched_company) or _is_blank(ja.matched_role):
                stats.still_unresolved += 1
            continue

        if not needs_fill(ja.matched_company, ja.matched_role):
            continue

        before_company_blank = _is_blank(ja.matched_company)
        before_role_blank = _is_blank(ja.matched_role)

        ex = extract_company_role(email, allow_llm_company=True, allow_llm_role=True)
        if ex.company_method == "llm" or ex.role_method == "llm":
            stats.llm_usage_count += 1

        changed = False
        if before_company_blank and ex.company:
            ja.matched_company = ex.company
            changed = True
            stats.filled_company += 1
            stats.resolved_company_count += 1
        if before_role_blank and ex.role:
            ja.matched_role = ex.role
            changed = True
            stats.filled_role += 1
            stats.resolved_role_heuristic += 1
            stats.resolved_role_count += 1

        if changed:
            stats.updated_rows += 1
            session.add(ja)
            session.commit()
            session.refresh(ja)

        if before_company_blank:
            if not _is_blank(ja.matched_company):
                if ex.company_method == "domain":
                    stats.resolved_company_domain += 1
                elif ex.company_method == "subject":
                    stats.resolved_company_subject += 1
                elif ex.company_method == "body":
                    stats.resolved_company_body += 1
                elif ex.company_method == "llm":
                    stats.resolved_company_llm += 1
            else:
                stats.unresolved_company += 1

        if before_role_blank and _is_blank(ja.matched_role):
            stats.unresolved_role += 1

        if _is_blank(ja.matched_company) or _is_blank(ja.matched_role):
            stats.still_unresolved += 1

    logger.info(
        "[BACKFILL] scanned=%s updated_rows=%s filled_company=%s filled_role=%s "
        "resolved_company_count=%s resolved_role_count=%s llm_usage_count=%s still_unresolved_rows=%s "
        "company_resolved(domain=%s subject=%s body=%s llm=%s unresolved=%s) "
        "role_heuristic=%s role_unresolved=%s",
        stats.scanned,
        stats.updated_rows,
        stats.filled_company,
        stats.filled_role,
        stats.resolved_company_count,
        stats.resolved_role_count,
        stats.llm_usage_count,
        stats.still_unresolved,
        stats.resolved_company_domain,
        stats.resolved_company_subject,
        stats.resolved_company_body,
        stats.resolved_company_llm,
        stats.unresolved_company,
        stats.resolved_role_heuristic,
        stats.unresolved_role,
    )

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with Session(engine) as session:
        # Ensure per-run counters/cache are isolated for this CLI execution.
        from app.services.llm_cache import reset_cache

        reset_cache()
        backfill_job_application_company_role(session)


if __name__ == "__main__":
    main()
