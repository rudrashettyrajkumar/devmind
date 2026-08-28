"""Structured JSON logging with a per-session-id context, so every line a run emits
is greppable by session (docs/01-solution-design.md §15).
"""

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Final

_session_id_var: Final[ContextVar[str | None]] = ContextVar("devmind_session_id", default=None)


class SessionIdBinder:
    """Binds a session id to the current async context for the duration of a `with` block.

    Any log record emitted while bound carries `session_id` in its JSON output, without
    every call site having to pass it explicitly.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._token: Token[str | None] | None = None

    def __enter__(self) -> "SessionIdBinder":
        self._token = _session_id_var.set(self._session_id)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._token is not None:
            _session_id_var.reset(self._token)


class _SessionIdFilter(logging.Filter):
    """Injects the current contextvar's session id onto every record it sees."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = _session_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line — the shape a log aggregator or `jq` expects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": getattr(record, "session_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class LoggingConfigurator:
    """Configures the standard library `logging` module for the whole application.

    One call at process startup (from the application lifespan); every subsequent
    `logging.getLogger(__name__)` call anywhere in the codebase picks up the JSON
    formatter and the session-id filter automatically.
    """

    def configure(self, level: str = "INFO") -> None:
        root = logging.getLogger()
        root.setLevel(level.upper())

        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        handler.addFilter(_SessionIdFilter())

        root.handlers.clear()
        root.addHandler(handler)
