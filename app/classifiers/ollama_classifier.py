from __future__ import annotations

import json
from dataclasses import dataclass
import re
from typing import Any, Literal, Optional

import httpx

from app.config import settings
from app.email.preprocess import NormalizedEmail


Category = Literal[
    "not_job_related",
    "application_received",
    "rejected",
    "interview",
    "offer",
    "other_job_related",
]


@dataclass(frozen=True)
class LLMResult:
    is_job_related: bool
    category: Category
    company: Optional[str]
    role: Optional[str]
    confidence: float
    reason: Optional[str]


SYSTEM_PROMPT = """You classify personal inbox emails related to job applications.
Return ONLY valid JSON. No markdown. No extra text.

Rules:
- If the email is not about a job application or recruiting, set is_job_related=false and category="not_job_related".
- Job-board newsletters, job recommendations, "jobs you may like", and marketing blasts are NOT job applications.
  If it's only recommending roles and does not confirm that the user applied, set is_job_related=false.
- If it confirms a submitted application / application was received, category="application_received".
- If it says the candidate is not proceeding / rejected, category="rejected".
- If it invites to interview / screening, category="interview".
- If it contains an offer, category="offer".
- If it's job-related but not one of the above, category="other_job_related".

Extract:
- company: company name if present, else null
- role: role/title if present, else null

confidence: number between 0 and 1.
"""


def _build_user_prompt(email: NormalizedEmail) -> str:
    subject = email.subject or ""
    from_domain = email.from_domain or ""
    body = email.body_for_detection or ""
    # Limit to a reasonable size to keep Ollama fast.
    body = body[:3500]
    return f"""FromDomain: {from_domain}
Subject: {subject}
Body:
{body}
"""


def _parse_json(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    try:
        return json.loads(content)
    except Exception:
        # Fallback: extract the first JSON object from the response.
        # Handles models that wrap JSON in prose or ```json fences.
        content = re.sub(r"^```json\\s*|\\s*```$", "", content, flags=re.IGNORECASE | re.MULTILINE).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def classify_with_ollama(email: NormalizedEmail) -> LLMResult:
    """
    Calls a local Ollama server and returns a structured classification.
    Requires Ollama running on settings.ollama_base_url.
    """

    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "temperature": 0.1,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(email)},
        ],
        "stream": False,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = ((data.get("message") or {}).get("content")) or ""
    parsed = _parse_json(content)

    is_job_related = bool(parsed.get("is_job_related", False))
    category = parsed.get("category") or ("other_job_related" if is_job_related else "not_job_related")
    company = parsed.get("company")
    role = parsed.get("role")
    raw_conf = parsed.get("confidence", 0.5)
    try:
        confidence = float(0.5 if raw_conf is None else raw_conf)
    except Exception:
        confidence = 0.5
    reason = parsed.get("reason")

    # Coerce/guard
    if category not in {
        "not_job_related",
        "application_received",
        "rejected",
        "interview",
        "offer",
        "other_job_related",
    }:
        category = "other_job_related" if is_job_related else "not_job_related"

    if not is_job_related:
        category = "not_job_related"

    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0

    def _clean(s: Any) -> Optional[str]:
        if not isinstance(s, str):
            return None
        s = s.strip()
        return s or None

    return LLMResult(
        is_job_related=is_job_related,
        category=category,  # type: ignore[arg-type]
        company=_clean(company),
        role=_clean(role),
        confidence=confidence,
        reason=_clean(reason),
    )

