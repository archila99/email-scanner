from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    agent: str
    started_at: dt.datetime
    finished_at: dt.datetime
    details: dict[str, Any]
    error: Optional[str] = None

