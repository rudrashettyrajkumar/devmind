"""Shared setup for the approval-gate safety tests.

Builds a real `ApprovalService` over in-memory repositories and drives a session to
whichever gate state a test needs. Fakes nothing about the gate itself — only the
work that would precede it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import SessionStatus
from devmind.repositories import ApprovalRepository, EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from devmind.services.approval_service import ApprovalService
from devmind.services.remote_operation_guard import RemoteOperationGuard
from devmind.services.session_state_machine import SessionStateMachine

_PATH_TO_SUMMARIZING = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)


class GateHarness:
    """An `ApprovalService`, its guard, and a session id parked at `SUMMARIZING`."""

    def __init__(self, db_session: SQLAlchemySession) -> None:
        self.sessions = SessionRepository(db_session)
        self.events = EventRepository(db_session)
        self.machine = SessionStateMachine(self.sessions, self.events)
        self.service = ApprovalService(
            ApprovalRepository(db_session), self.sessions, self.machine, self.events
        )
        self.guard = RemoteOperationGuard(self.service)

        model = self.sessions.create(
            SessionCreate(repo_url="https://github.com/x/y", issue_number=1)
        )
        self.session_id = model.id
        for step in _PATH_TO_SUMMARIZING:
            self.machine.transition(self.session_id, step)
