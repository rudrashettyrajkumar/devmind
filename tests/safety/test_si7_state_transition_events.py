"""SI-7: every state transition is persisted before it takes effect.

`SessionStateMachine.transition()` is the only code that changes a session's status,
and it always appends a `STATE_CHANGED` event in the same call. A session is
replayable from its event log because of this. A regression here is a broken
invariant — fix the code, never the test.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import ApprovalDecision, EventType, SessionStatus
from devmind.repositories import EventRepository
from tests.safety._approval_kit import GateHarness

_WALK = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)


def test_si7_every_transition_emits_a_state_changed_event(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)  # already walked CREATED → SUMMARIZING
    events = EventRepository(db_session).list_since(harness.session_id)
    state_changes = [e.payload for e in events if e.event_type is EventType.STATE_CHANGED]

    assert [change["to"] for change in state_changes] == [step.value for step in _WALK]
    for change in state_changes:
        assert change["from"] and change["to"]


async def test_si7_approval_transitions_are_also_logged(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    await harness.service.request(harness.session_id)
    await harness.service.decide(harness.session_id, ApprovalDecision.APPROVED, decided_by="alice")

    tos = [
        e.payload["to"]
        for e in EventRepository(db_session).list_since(harness.session_id)
        if e.event_type is EventType.STATE_CHANGED
    ]
    assert tos[-2:] == [
        SessionStatus.AWAITING_APPROVAL.value,
        SessionStatus.APPROVED.value,
    ]
