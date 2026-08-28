"""Data access for the append-only event log. `append()` never overwrites and never
updates — every session's history is replayable in order because `sequence` is
monotonic, gap-free, and unique per session.
"""

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from devmind.core.constants import EVENT_SEQUENCE_MAX_ATTEMPTS
from devmind.core.enums import EventType
from devmind.models.event import EventModel


class EventRepository:
    """Appends to and reads from one session's event log."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self, session_id: str, event_type: EventType, payload: Mapping[str, object]
    ) -> EventModel:
        """Allocates the next sequence atomically and inserts.

        The allocation is `SELECT MAX(sequence)+1` inside the same transaction as the
        insert, backstopped by the `(session_id, sequence)` unique constraint: if two
        writers compute the same next sequence, the second's commit raises
        `IntegrityError`, and it retries once against the sequence the first writer
        just claimed. `DatabaseManager`'s SQLite `timeout` (core/database.py) means
        this is resolving a genuine sequence race, not a lock-contention timeout.
        """
        last_error: IntegrityError | None = None
        for _ in range(EVENT_SEQUENCE_MAX_ATTEMPTS):
            event = EventModel(
                session_id=session_id,
                sequence=self._next_sequence(session_id),
                event_type=event_type,
                payload=dict(payload),
            )
            self._session.add(event)
            try:
                self._session.commit()
            except IntegrityError as exc:
                self._session.rollback()
                last_error = exc
                continue
            else:
                self._session.refresh(event)
                return event
        assert last_error is not None  # loop always runs >= 1 time (constant >= 1)
        raise last_error

    def list_since(
        self, session_id: str, after_sequence: int = 0, limit: int = 200
    ) -> list[EventModel]:
        stmt = (
            select(EventModel)
            .where(EventModel.session_id == session_id, EventModel.sequence > after_sequence)
            .order_by(EventModel.sequence)
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())

    def count(self, session_id: str) -> int:
        stmt = (
            select(func.count()).select_from(EventModel).where(EventModel.session_id == session_id)
        )
        return self._session.execute(stmt).scalar_one()

    def _next_sequence(self, session_id: str) -> int:
        stmt = select(func.coalesce(func.max(EventModel.sequence), 0)).where(
            EventModel.session_id == session_id
        )
        current_max: int = self._session.execute(stmt).scalar_one()
        return current_max + 1
