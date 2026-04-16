from __future__ import annotations

"""
Company Insight Agent

This module is intentionally lightweight and only provides a callable function
that can be used when explicitly triggered (e.g., for interviews).

It reuses the existing Ollama single-flight executor.
"""

import datetime as dt
from typing import Optional

from app.services.ollama_executor import run_ollama_safe
from app.config import settings


def generate_company_insight(*, company_name: str, role: Optional[str] = None) -> str:
    """
    Optional LLM helper. Keep prompt small; runs through global Ollama lock.
    """
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    role_part = f"Role: {role}\n" if role else ""
    prompt = (
        "Return a concise company insight for interview prep. "
        "Focus on what the company does, recent themes, and 5 questions to ask.\n\n"
        f"Company: {company_name}\n"
        f"{role_part}"
        f"Date: {dt.date.today().isoformat()}\n"
    )
    payload = {
        "model": settings.ollama_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are a concise career coach. Return plain text."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    data = run_ollama_safe(url=url, payload=payload, tag="company_insight")
    content = ((data.get("message") or {}).get("content")) or ""
    return (content or "").strip()

