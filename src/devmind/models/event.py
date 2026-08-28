"""The append-only event log. See docs/01-solution-design.md §11 and §15."""

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from devmind.core.enums import EventType
from devmind.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class EventModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One entry in a session's audit trail. Never updated, never deleted.

    `(session_id, sequence)` is unique — the backstop `EventRepository.append()`
    relies on when two writers briefly compute the same next sequence (see
    `core/constants.py::EVENT_SEQUENCE_MAX_ATTEMPTS`).
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_events_session_sequence"),
    )

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    sequence: Mapped[int]
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
