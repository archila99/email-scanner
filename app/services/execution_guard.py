from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore


@dataclass
class FileLock:
    path: Path
    _fd: Optional[int] = None

    def acquire(self, *, blocking: bool) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        if fcntl is None:
            # Best-effort fallback: pretend we acquired (single-process safety only).
            self._fd = fd
            return True

        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            os.close(fd)
            return False
        self._fd = fd
        # Touch lock file with PID + timestamp for debugging.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()} acquired_at={int(time.time())}\n".encode("utf-8"))
            os.fsync(fd)
        except Exception:
            pass
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(self._fd)
        finally:
            self._fd = None


def ingestion_lock() -> FileLock:
    # Use a stable system temp location; safe for single-machine deployments.
    return FileLock(path=Path("/tmp/gmail_scanner_ingest.lock"))


def ollama_lock() -> FileLock:
    return FileLock(path=Path("/tmp/gmail_scanner_ollama.lock"))

