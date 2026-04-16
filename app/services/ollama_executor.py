from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.services.execution_guard import ollama_lock
from app.services.llm_cache import incr_ollama_call_count

logger = logging.getLogger(__name__)


def run_ollama_safe(*, url: str, payload: dict[str, Any], tag: str, delay_s: float = 0.15) -> dict[str, Any]:
    """
    Safety wrapper around ALL Ollama HTTP calls.

    - Global single-flight (max=1) across process via file lock
    - Optional small delay to smooth load
    - Timing + call count logging
    """
    lock = ollama_lock()
    acquired = lock.acquire(blocking=True)
    if not acquired:
        # With blocking=True this should not happen, but keep a sane fallback.
        logger.warning("[OLLAMA] could not acquire lock tag=%s", tag)

    start = time.perf_counter()
    try:
        if delay_s and delay_s > 0:
            time.sleep(delay_s)

        call_no = incr_ollama_call_count()
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info("[OLLAMA] call=%s tag=%s elapsed_ms=%.0f", call_no, tag, elapsed_ms)
        return data
    finally:
        try:
            lock.release()
        except Exception:
            pass

