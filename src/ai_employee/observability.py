"""Logging configuration and per-request correlation.

Every module logs through `logging.getLogger(__name__)` and nothing else touches handlers.
This is the one place a process decides where those records go, and each entrypoint - the
API, the ingestion CLI, the agent CLI - calls `configure_logging()` before doing any work.

Without it the API is effectively silent: uvicorn configures only its own loggers, leaving
`ai_employee.*` at the root's default WARNING with no handler attached, so every INFO line
in the codebase is discarded and errors escape through logging's bare last-resort handler.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from ai_employee.config import get_settings

# Bound for the duration of one HTTP request or one CLI turn, so every record emitted while
# handling it can be grouped afterwards. "-" means nothing is in flight.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_UNSET = "-"
_TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"

# Ids may arrive from a caller's header, and a record is a line in a log file: anything
# outside this set could forge a second line.
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")

_configured = False


class _RequestIdFilter(logging.Filter):
    """Puts the current request id on every record so the formatter can rely on it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log shipper that parses rather than greps."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", _UNSET),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """Attach one stderr handler to the root logger. Safe to call more than once."""
    global _configured
    if _configured:
        return

    settings = get_settings()
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        _JsonFormatter() if settings.log_format == "json" else logging.Formatter(_TEXT_FORMAT)
    )

    root = logging.getLogger()
    root.handlers = [handler]
    # The root stays at WARNING and only our own tree follows LOG_LEVEL. The Azure and HTTP
    # SDKs log every request at INFO and every header at DEBUG; a root set to DEBUG buries
    # the ingestion run in someone else's traffic.
    root.setLevel(logging.WARNING)
    resolved = level or settings.log_level
    # "__main__" alongside the package tree: `python -m ai_employee.agent.runner` executes
    # that module as __main__, so its getLogger(__name__) lands outside ai_employee.* and
    # would otherwise be held at the root's WARNING.
    for name in ("ai_employee", "__main__"):
        logging.getLogger(name).setLevel(resolved)
    _configured = True


def clean_request_id(value: str | None) -> str | None:
    """Normalise an id supplied by a caller, or None if there is nothing usable in it."""
    if not value:
        return None
    cleaned = _SAFE_ID.sub("", value)[:64]
    return cleaned or None


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Bind an id for the work done inside. An id already in scope is kept, so a CLI turn
    generates one and the same turn under the API inherits the HTTP request's."""
    current = _request_id.get()
    resolved = clean_request_id(request_id) or (
        current if current != _UNSET else uuid.uuid4().hex[:12]
    )
    token = _request_id.set(resolved)
    try:
        yield resolved
    finally:
        _request_id.reset(token)


def current_request_id() -> str | None:
    """The id bound to the work in flight, or None outside any."""
    request_id = _request_id.get()
    return None if request_id == _UNSET else request_id


def truncate(text: str, limit: int = 200) -> str:
    """Shorten free text destined for a log line."""
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}…"