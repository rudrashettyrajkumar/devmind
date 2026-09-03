"""`ApprovalService` — the gate's happy paths and every illegal call (E9-F2).

Proves: `request()` runs only from `SUMMARIZING`; `decide()` runs only from
`AWAITING_APPROVAL`, once; `decided_by` is required; a rejection needs a reason; a
second decision raises. See `tests/safety/` for the invariant-level checks.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import ApprovalDecision, EventType, SessionStatus
from devmind.exceptions import (
    ApprovalDecisionError,
    ApprovalRequiredError,
    InvalidStateTransitionError,
    SessionNotFoundError,
)
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


def _make_service(db_session: SQLAlchemySession) -> ApprovalService:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    return ApprovalService(
        ApprovalRepository(db_session),
        sessions,
        SessionStateMachine(sessions, events),
        events,
    )


def _session_at(db_session: SQLAlchemySession, status: SessionStatus) -> str:
    repo = SessionRepository(db_session)
    machine = SessionStateMachine(repo, EventRepository(db_session))
    model = repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=7))
    for step in _TO_SUMMARIZING:
        machine.transition(model.id, step)
        if step is status:
            return model.id
    return model.id


@pytest.fixture
def service(db_session: SQLAlchemySession) -> ApprovalService:
    return _make_service(db_session)


async def test_request_moves_summarizing_to_awaiting_approval(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)

    record = await service.request(session_id)

    assert record.token
    assert record.decision is None
    assert SessionRepository(db_session).get_by_id(session_id).status is (
        SessionStatus.AWAITING_APPROVAL
    )
    types = {e.event_type for e in EventRepository(db_session).list_since(session_id)}
    assert EventType.APPROVAL_REQUESTED in types


async def test_request_from_wrong_state_raises_and_creates_nothing(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.EDITING)

    with pytest.raises(InvalidStateTransitionError):
        await service.request(session_id)

    assert ApprovalRepository(db_session).get_by_session(session_id) is None


async def test_request_unknown_session_raises(service: ApprovalService) -> None:
    with pytest.raises(SessionNotFoundError):
        await service.request("no-such-session")


async def test_decide_approves_and_records_the_human(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)

    record = await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")

    assert record.decision is ApprovalDecision.APPROVED
    assert record.decided_by == "alice"
    assert record.decided_at is not None
    assert SessionRepository(db_session).get_by_id(session_id).status is SessionStatus.APPROVED
    payloads = [
        e.payload
        for e in EventRepository(db_session).list_since(session_id)
        if e.event_type is EventType.APPROVAL_DECIDED
    ]
    assert payloads == [{"decision": "approved", "decided_by": "alice", "reason": None}]


async def test_decide_rejects_with_a_reason(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)

    record = await service.decide(
        session_id, ApprovalDecision.REJECTED, decided_by="bob", reason="scope too broad"
    )

    assert record.decision is ApprovalDecision.REJECTED
    assert record.reason == "scope too broad"
    assert SessionRepository(db_session).get_by_id(session_id).status is SessionStatus.REJECTED


async def test_decide_requires_a_named_human(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)

    with pytest.raises(ApprovalDecisionError):
        await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="   ")


async def test_rejection_without_a_reason_raises(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)

    with pytest.raises(ApprovalDecisionError):
        await service.decide(session_id, ApprovalDecision.REJECTED, decided_by="bob")


async def test_decide_before_request_raises(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)

    with pytest.raises(ApprovalRequiredError):
        await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")


async def test_second_decision_is_refused(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)
    await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")

    with pytest.raises(ApprovalDecisionError):
        await service.decide(session_id, ApprovalDecision.REJECTED, decided_by="bob", reason="no")


async def test_assert_approved_returns_the_record_then_flags_consumption(
    service: ApprovalService, db_session: SQLAlchemySession
) -> None:
    session_id = _session_at(db_session, SessionStatus.SUMMARIZING)
    await service.request(session_id)
    await service.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")

    record = await service.assert_approved(session_id)
    assert record.is_actionable

    await service.consume(session_id)
    from devmind.exceptions import ApprovalAlreadyConsumedError

    with pytest.raises(ApprovalAlreadyConsumedError):
        await service.assert_approved(session_id)
