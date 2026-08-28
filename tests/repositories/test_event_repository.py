from devmind.core.enums import EventType
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate


def _make_session(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_first_append_starts_at_sequence_one(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_id = _make_session(session_repo)
    event = event_repo.append(session_id, EventType.SESSION_CREATED, {})
    assert event.sequence == 1


def test_sequence_is_monotonic_and_gap_free(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_id = _make_session(session_repo)
    sequences = [
        event_repo.append(session_id, EventType.LLM_CALL, {"n": i}).sequence for i in range(5)
    ]
    assert sequences == [1, 2, 3, 4, 5]


def test_sequences_are_independent_per_session(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_a = _make_session(session_repo)
    session_b = _make_session(session_repo)
    event_repo.append(session_a, EventType.LLM_CALL, {})
    first_b = event_repo.append(session_b, EventType.LLM_CALL, {})
    assert first_b.sequence == 1


def test_payload_roundtrips(event_repo: EventRepository, session_repo: SessionRepository) -> None:
    session_id = _make_session(session_repo)
    event = event_repo.append(
        session_id, EventType.TOOL_CALL, {"tool": "read_file", "path": "a.py"}
    )
    assert event.payload == {"tool": "read_file", "path": "a.py"}


def test_list_since_returns_in_order(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_id = _make_session(session_repo)
    for i in range(5):
        event_repo.append(session_id, EventType.LLM_CALL, {"n": i})
    events = event_repo.list_since(session_id)
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5]


def test_list_since_paginates_by_after_sequence(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_id = _make_session(session_repo)
    for i in range(5):
        event_repo.append(session_id, EventType.LLM_CALL, {"n": i})
    events = event_repo.list_since(session_id, after_sequence=2)
    assert [e.sequence for e in events] == [3, 4, 5]


def test_list_since_respects_limit(
    event_repo: EventRepository, session_repo: SessionRepository
) -> None:
    session_id = _make_session(session_repo)
    for i in range(5):
        event_repo.append(session_id, EventType.LLM_CALL, {"n": i})
    events = event_repo.list_since(session_id, limit=2)
    assert [e.sequence for e in events] == [1, 2]


def test_count(event_repo: EventRepository, session_repo: SessionRepository) -> None:
    session_id = _make_session(session_repo)
    assert event_repo.count(session_id) == 0
    event_repo.append(session_id, EventType.LLM_CALL, {})
    event_repo.append(session_id, EventType.LLM_CALL, {})
    assert event_repo.count(session_id) == 2
