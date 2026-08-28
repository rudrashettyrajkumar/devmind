"""The single place that *acts* on a session status transition.

`SessionStatus.can_transition_to()` (core/enums.py) only answers whether a move is
legal — pure, no I/O. This class is what actually persists the move and records it,
and it is the only thing anywhere in the codebase allowed to change a session's
status. That's what makes `PR_OPENED` reachable only through `APPROVED` (docs/
01-solution-design.md §9, safety layer 2): there is exactly one code path that
changes status, and it refuses anything the legal-transition map doesn't allow.
"""

from devmind.core.enums import EventType, SessionStatus
from devmind.exceptions import InvalidStateTransitionError, SessionNotFoundError
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.session import SessionRead


class SessionStateMachine:
    """Validates and performs one session's status transitions."""

    def __init__(self, sessions: SessionRepository, events: EventRepository) -> None:
        self._sessions = sessions
        self._events = events

    def transition(
        self, session_id: str, target: SessionStatus, *, reason: str | None = None
    ) -> SessionRead:
        """Moves `session_id` to `target`, persists it, and emits `STATE_CHANGED`.

        Returns a `SessionRead`, not the ORM `SessionModel` — repositories return ORM
        models (Claude.md §3), but this is a service, and services convert to schemas
        (§2) rather than let an ORM object cross back out to whatever calls them.

        Raises `InvalidStateTransitionError` — and changes nothing — if `target` is
        not a legal move from the session's current status. Raises
        `SessionNotFoundError` (via the repository) if the session doesn't exist.
        """
        current_session = self._sessions.get_by_id(session_id)
        if current_session is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )

        current_status = current_session.status
        if not current_status.can_transition_to(target):
            raise InvalidStateTransitionError(
                f"cannot transition session {session_id} from {current_status.value} "
                f"to {target.value}",
                details={
                    "session_id": session_id,
                    "from": current_status.value,
                    "to": target.value,
                },
            )

        updated = self._sessions.update_status(session_id, target, failure_reason=reason)
        self._events.append(
            session_id,
            EventType.STATE_CHANGED,
            {"from": current_status.value, "to": target.value, "reason": reason},
        )
        return SessionRead.model_validate(updated)
