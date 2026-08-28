"""Request/response DTOs for the session event log."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from devmind.core.enums import EventType


class EventRead(BaseModel):
    """One entry from a session's audit trail, as returned by `GET /sessions/{id}/events`
    (E11) and streamed over SSE (`EventStreamService`, E11).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    sequence: int
    event_type: EventType
    payload: dict[str, object]
    created_at: datetime
