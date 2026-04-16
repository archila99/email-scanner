from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import settings
from app.email.preprocess import NormalizedEmail


@dataclass(frozen=True)
class CompanyExtractResult:
    company: Optional[str]
    role: Optional[str]
    confidence: float
    reason: Optional[str]


SYSTEM_PROMPT = """You extract the employer/company name for a job-application email.
Return ONLY valid JSON. No markdown. No extra text.

Goal:
- Identify the company the email is about (the employer / hiring organization), not the ATS vendor.

Rules:
- Prefer explicit mentions in Subject, then first ~2 paragraphs of Body.
- If the email is from an ATS domain (greenhouse.io, lever.co, workday.com, ashbyhq.com, etc.) do NOT treat the domain as the company.
- If you cannot confidently name a specific company, return company=null.
- role is optional; return null if unknown.

Return JSON only with keys:
{
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
        content = re.sub(r"^```json\\s*|\\s*```$", "", content, flags=re.IGNORECASE | re.MULTILINE).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def extract_company_with_ollama(email: NormalizedEmail) -> CompanyExtractResult:
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

    company = parsed.get("company")
    role = parsed.get("role")
    raw_conf = parsed.get("confidence", 0.5)
    try:
        confidence = float(0.5 if raw_conf is None else raw_conf)
    except Exception:
        confidence = 0.5
    reason = parsed.get("reason")

    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0

    def _clean(s: Any) -> Optional[str]:
        if not isinstance(s, str):
            return None
        s = s.strip()
        return s or None

    return CompanyExtractResult(
        company=_clean(company),
        role=_clean(role),
        confidence=confidence,
        reason=_clean(reason),
    )
