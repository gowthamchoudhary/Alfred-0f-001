"""Structured logging for the Alfred pipeline.

Every pipeline step writes timestamped event lines in the shape the
dashboard timeline consumes:

    "[HH:MM:SS] STEP_NAME   message"

Events go to three places at once:
  * stdout (CLI visibility),
  * the ``agent_events`` SQLite table (durable, feeds the dashboard), and
  * a small in-memory ring buffer (cheap live tail for the API while an
    investigation is running).
"""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import Deque

from .db import Database

_BUFFER_SIZE = 500
_buffer: Deque[dict] = deque(maxlen=_BUFFER_SIZE)
_buffer_lock = threading.Lock()


def format_event_line(step: str, message: str, timestamp: float | None = None) -> str:
    ts = time.strftime("%H:%M:%S", time.localtime(timestamp if timestamp is not None else time.time()))
    return f"[{ts}] {step:<12} {message}"


def log_event(
    db: Database,
    investigation_id: str,
    step: str,
    message: str,
    level: str = "info",
) -> None:
    line = format_event_line(step, message)
    print(line, flush=True)
    db.log_event(investigation_id, step, message, level)
    with _buffer_lock:
        _buffer.append(
            {
                "investigation_id": investigation_id,
                "step": step,
                "message": message,
                "level": level,
                "created_at": time.time(),
                "line": line,
            }
        )


def recent_events(limit: int = 100) -> list[dict]:
    """Newest-first snapshot of the in-memory event buffer."""
    with _buffer_lock:
        items = list(_buffer)
    return list(reversed(items[-limit:]))
