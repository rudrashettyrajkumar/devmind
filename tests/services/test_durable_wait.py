"""Durable wait — `AWAITING_APPROVAL` outlives a restart and is still decidable (E9-F2-T4).

There is no timeout and no auto-approve: the state is simply persisted. A fresh set
of repositories on a new connection (standing in for a process restart) can read the
pending approval and decide it.
"""

from __future__ import annotations

from devmind.core.database import DatabaseManager
from devmind.core.enums import ApprovalDecision, SessionStatus
from devmind.repositories import ApprovalRepository, EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from devmind.services.approval_service import ApprovalService
from devmind.services.session_state_machine import SessionStateMachine

_TO_SUMMARIZING = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)


async def test_awaiting_approval_survives_a_simulated_restart(db: DatabaseManager) -> None:
    # --- process 1: run up to the gate, then "crash" -----------------------
    with db.session_scope() as scope:
        sessions = SessionRepository(scope)
        events = EventRepository(scope)
        machine = SessionStateMachine(sessions, events)
        service = ApprovalService(ApprovalRepository(scope), sessions, machine, events)
        model = sessions.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=1))
        session_id = model.id
        for step in _TO_SUMMARIZING:
            machine.transition(session_id, step)
        await service.request(session_id)

    # --- process 2: fresh connection, no in-memory state ------------------
    with db.session_scope() as scope:
        sessions = SessionRepository(scope)
        row = sessions.get_by_id(session_id)
        assert row is not None
        assert row.status is SessionStatus.AWAITING_APPROVAL
        assert row.completed_at is None  # nothing auto-decided it while "down"

        events = EventRepository(scope)
        machine = SessionStateMachine(sessions, events)
        service = ApprovalService(ApprovalRepository(scope), sessions, machine, events)
        record = await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="dana")
        assert record.is_approved

    with db.session_scope() as scope:
        row = SessionRepository(scope).get_by_id(session_id)
        assert row is not None
        assert row.status is SessionStatus.APPROVED
