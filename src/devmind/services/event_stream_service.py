"""`EventStreamService` — the SSE live feed over a session's event log (E11-F3).

Polls the event table every `poll_interval` seconds and yields each new row as an
already-encoded SSE frame. This is deliberately a poll, not an in-process pub/sub:
one process, a local database, and a half-second latency budget do not justify that
infrastructure (Claude.md §9, spec §"SSE streaming").

Guarantees:

* **Resumable.** `after_sequence` (the router fills it from `Last-Event-ID`) means a
  reconnect replays from the log rather than losing the gap — the whole reason
  `EventModel.sequence` is monotonic and unique.
* **Heartbeat.** An SSE comment every `heartbeat_interval` seconds so a proxy does
  not kill an idle connection during a long test run.
* **Bounded.** The stream ends once the session reaches a terminal status, after the
  final batch of events has been flushed.
* **Leak-free.** Every DB read is its own short `session_scope()`; there is no
  long-held `Session`, and `GeneratorExit` / `CancelledError` on client disconnect
  simply stops the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from devmind.core.constants import (
    SSE_HEARTBEAT_INTERVAL_SECONDS,
    SSE_POLL_INTERVAL_SECONDS,
    SSE_STREAM_BATCH_LIMIT,
)
from devmind.core.database import DatabaseManager
from devmind.exceptions import SessionNotFoundError
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.event import EventRead
from devmind.schemas.stream import SSE_HEARTBEAT, ServerSentEvent

logger = logging.getLogger(__name__)


class EventStreamService:
    """Turns one session's growing event log into an SSE byte stream."""

    def __init__(
        self,
        database: DatabaseManager,
        *,
        poll_interval: float = SSE_POLL_INTERVAL_SECONDS,
        heartbeat_interval: float = SSE_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._database = database
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval

    def assert_session_exists(self, session_id: str) -> None:
        """Raise `SessionNotFoundError` if there is no such session.

        The router calls this before returning the `StreamingResponse` — its own
        `session_scope()` opens and closes here, so no write lock is held while the
        long-lived stream polls (SQLite serialises write transactions).
        """
        with self._database.session_scope() as db:
            if SessionRepository(db).get_by_id(session_id) is None:
                raise SessionNotFoundError(
                    f"session {session_id} not found", details={"session_id": session_id}
                )

    async def stream(self, session_id: str, after_sequence: int = 0) -> AsyncIterator[str]:
        """Yield encoded SSE frames for `session_id`, starting after `after_sequence`.

        Yields already-encoded strings (`ServerSentEvent.encode()` output and
        heartbeat comments) so the router only has to wrap this in a
        `StreamingResponse` — it holds no domain knowledge.
        """
        cursor = after_sequence
        idle = 0.0
        try:
            while True:
                events, terminal = self._poll(session_id, cursor)
                for event in events:
                    yield ServerSentEvent(
                        id=event.sequence,
                        event=event.event_type.value,
                        data=dict(event.payload),
                    ).encode()
                    cursor = event.sequence

                if events:
                    idle = 0.0
                elif (idle := idle + self._poll_interval) >= self._heartbeat_interval:
                    yield SSE_HEARTBEAT
                    idle = 0.0

                if terminal:
                    logger.debug("session %s reached a terminal status; closing stream", session_id)
                    return

                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.debug("SSE stream for session %s cancelled (client disconnect)", session_id)
            raise

    def _poll(self, session_id: str, after_sequence: int) -> tuple[list[EventRead], bool]:
        """One short unit of work: the next batch of events (projected to schemas, so
        nothing ORM-bound escapes the scope) and whether the session has finished.
        Its own `session_scope()` — no `Session` is held between polls.
        """
        with self._database.session_scope() as db:
            rows = EventRepository(db).list_since(
                session_id, after_sequence, limit=SSE_STREAM_BATCH_LIMIT
            )
            model = SessionRepository(db).get_by_id(session_id)
            terminal = model is not None and model.status.is_terminal()
            return [EventRead.model_validate(row) for row in rows], terminal
