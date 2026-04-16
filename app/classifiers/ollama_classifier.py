from __future__ import annotations

import json
from dataclasses import dataclass
import re
from typing import Any, Literal, Optional

from app.config import settings
from app.email.preprocess import NormalizedEmail
from app.services.llm_cache import CachedLLM, cache_put
from app.services.ollama_executor import run_ollama_safe


Type = Literal["application", "rejection", "interview", "offer", "other", "not_job_related"]


@dataclass(frozen=True)
class LLMResult:
    type: Type
    company: Optional[str]
    role: Optional[str]
    confidence: float
    reason: Optional[str]


SYSTEM_PROMPT = """You are an email classifier for job applications.
Return ONLY valid JSON. No markdown. No extra text.

Only classify emails that are specifically about the user's own job applications.
Do NOT classify recruiter outreach, job ads, recommendations, newsletters, job alerts,
or marketing from job websites as application emails.

Classify the email into ONE of:
- application (confirmation)
- rejection
- interview
- offer
- other
- not_job_related

Rules:
- "Unfortunately", "we regret" → rejection
- "We would like to invite", "invite you to interview" → interview
- "Offer" or "pleased to offer" → offer
- "Thank you for applying", "we received your application" → application
- If multiple phrases conflict, pick the strongest signal in this order:
  rejection > offer > interview > application > other > not_job_related
- Use `type="not_job_related"` for recruiter outreach, recommendations, job alerts, newsletters,
  marketing, or any email that is not clearly about an application the user already made.
- Extract `company` and `role` if mentioned in the subject or first paragraph of the body; otherwise return null.
- Confidence guidance:
  - strong explicit keyword/pattern match → 0.9 to 1.0
  - moderate but clear evidence → 0.7 to 0.89
  - weak inferred hints → 0.5 to 0.69
  - clearly not application-related → 0.9 to 1.0 with `type="not_job_related"`

Examples of `not_job_related`:
- "Our recommendation: ..."
- "jobs you may like"
- "job alert"
- recruiter outreach with no prior application
- training/course promotions

Return JSON only with keys:
{
  "type": "application|rejection|interview|offer|other|not_job_related",
  "company": string or null,
  "role": string or null,
  "confidence": number between 0 and 1,
  "reason": string or null
}
"""


def _build_user_prompt(email: NormalizedEmail) -> str:
    subject = email.subject or ""
    from_domain = email.from_domain or ""
    body = email.body_clean or ""
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

    data = run_ollama_safe(url=url, payload=payload, tag="classify")

    content = ((data.get("message") or {}).get("content")) or ""
    parsed = _parse_json(content)

    t = parsed.get("type") or "not_job_related"
    company = parsed.get("company")
    role = parsed.get("role")
    raw_conf = parsed.get("confidence", 0.5)
    try:
        confidence = float(0.5 if raw_conf is None else raw_conf)
    except Exception:
        confidence = 0.5
    reason = parsed.get("reason")

    # Coerce/guard
    if t not in {
        "not_job_related",
        "application",
        "rejection",
        "interview",
        "offer",
        "other",
    }:
        t = "not_job_related"

    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0

    def _clean(s: Any) -> Optional[str]:
        if not isinstance(s, str):
            return None
        s = s.strip()
        return s or None

    res = LLMResult(
        type=t,  # type: ignore[arg-type]
        company=_clean(company),
        role=_clean(role),
        confidence=confidence,
        reason=_clean(reason),
    )
    try:
        cache_put(
            _cache_key(email),
            CachedLLM(
                kind="classification",
                company=res.company,
                role=res.role,
                confidence=res.confidence,
                raw={"type": res.type, "company": res.company, "role": res.role, "confidence": res.confidence},
            ),
        )
    except Exception:
        pass
    return res


def _cache_key(email: NormalizedEmail) -> str:
    # Prefer stable provider id when present.
    return f"provider:{email.provider_message_id}"


