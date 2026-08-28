import pytest

from devmind.core.enums import EventType, SessionStatus
from devmind.exceptions import InvalidStateTransitionError, SessionNotFoundError
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from devmind.services.session_state_machine import SessionStateMachine


@pytest.fixture
def state_machine(
    session_repo: SessionRepository, event_repo: EventRepository
) -> SessionStateMachine:
    return SessionStateMachine(session_repo, event_repo)


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_legal_transition_persists_new_status(
    state_machine: SessionStateMachine, session_id: str
) -> None:
    updated = state_machine.transition(session_id, SessionStatus.INGESTING)
    assert updated.status is SessionStatus.INGESTING


def test_full_happy_path_sequence(state_machine: SessionStateMachine, session_id: str) -> None:
    path = [
        SessionStatus.INGESTING,
        SessionStatus.PLANNING,
        SessionStatus.INVESTIGATING,
        SessionStatus.EDITING,
        SessionStatus.TESTING,
        SessionStatus.SUMMARIZING,
        SessionStatus.AWAITING_APPROVAL,
        SessionStatus.APPROVED,
        SessionStatus.PR_OPENED,
    ]
    for target in path:
        updated = state_machine.transition(session_id, target)
        assert updated.status is target


def test_illegal_transition_raises_and_changes_nothing(
    state_machine: SessionStateMachine, session_id: str, session_repo: SessionRepository
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        state_machine.transition(session_id, SessionStatus.PR_OPENED)
    unchanged = session_repo.get_by_id(session_id)
    assert unchanged is not None
    assert unchanged.status is SessionStatus.CREATED


def test_transition_on_missing_session_raises(state_machine: SessionStateMachine) -> None:
    with pytest.raises(SessionNotFoundError):
        state_machine.transition("does-not-exist", SessionStatus.INGESTING)


def test_terminal_status_accepts_no_further_transition(
    state_machine: SessionStateMachine, session_id: str
) -> None:
    state_machine.transition(session_id, SessionStatus.FAILED)
    with pytest.raises(InvalidStateTransitionError):
        state_machine.transition(session_id, SessionStatus.INGESTING)


def test_reason_is_persisted_as_failure_reason(
    state_machine: SessionStateMachine, session_id: str, session_repo: SessionRepository
) -> None:
    state_machine.transition(session_id, SessionStatus.FAILED, reason="ingestion failed: 404")
    failed = session_repo.get_by_id(session_id)
    assert failed is not None
    assert failed.failure_reason == "ingestion failed: 404"


def test_each_transition_emits_exactly_one_state_changed_event(
    state_machine: SessionStateMachine, session_id: str, event_repo: EventRepository
) -> None:
    state_machine.transition(session_id, SessionStatus.INGESTING)
    state_machine.transition(session_id, SessionStatus.PLANNING)

    events = event_repo.list_since(session_id)
    state_changes = [e for e in events if e.event_type is EventType.STATE_CHANGED]
    assert len(state_changes) == 2
    assert state_changes[0].payload == {"from": "created", "to": "ingesting", "reason": None}
    assert state_changes[1].payload == {"from": "ingesting", "to": "planning", "reason": None}


def test_illegal_transition_emits_no_event(
    state_machine: SessionStateMachine, session_id: str, event_repo: EventRepository
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        state_machine.transition(session_id, SessionStatus.PR_OPENED)
    assert event_repo.count(session_id) == 0
