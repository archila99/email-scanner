from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CachedLLM:
    # Generic cached payloads
    kind: str  # "classification" | "extraction"
    company: Optional[str]
    role: Optional[str]
    confidence: Optional[float]
    raw: Any


_cache: ContextVar[dict[str, CachedLLM]] = ContextVar("_cache", default={})
_ollama_call_count: ContextVar[int] = ContextVar("_ollama_call_count", default=0)


def reset_cache() -> None:
    _cache.set({})
    _ollama_call_count.set(0)


def get_cache() -> dict[str, CachedLLM]:
    return _cache.get()


def cache_get(key: str) -> Optional[CachedLLM]:
    return _cache.get().get(key)


def cache_put(key: str, value: CachedLLM) -> None:
    d = dict(_cache.get())
    d[key] = value
    _cache.set(d)


def incr_ollama_call_count() -> int:
    n = int(_ollama_call_count.get() or 0) + 1
    _ollama_call_count.set(n)
    return n


def get_ollama_call_count() -> int:
    return int(_ollama_call_count.get() or 0)

