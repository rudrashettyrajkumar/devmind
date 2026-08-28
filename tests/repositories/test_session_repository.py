import pytest

from devmind.core.enums import SessionStatus
from devmind.exceptions import SessionNotFoundError
from devmind.repositories import SessionRepository
from devmind.schemas.session import SessionCreate


def test_create_persists_and_returns_the_model(
    session_repo: SessionRepository, session_create: SessionCreate
) -> None:
    model = session_repo.create(session_create)
    assert model.id
    assert model.repo_url == session_create.repo_url
    assert model.issue_number == 42
    assert model.status is SessionStatus.CREATED
    assert model.fix_attempts == 0
    assert model.estimated_cost_usd == 0.0


def test_create_from_free_text_description_populates_issue_body(
    session_repo: SessionRepository,
) -> None:
    data = SessionCreate(repo_url="https://github.com/a/b", issue_description="the button is red")
    model = session_repo.create(data)
    assert model.issue_number is None
    assert model.issue_title is None
    assert model.issue_body == "the button is red"


def test_get_by_id_returns_none_for_missing_id(session_repo: SessionRepository) -> None:
    assert session_repo.get_by_id("does-not-exist") is None


def test_get_by_id_roundtrips(
    session_repo: SessionRepository, session_create: SessionCreate
) -> None:
    created = session_repo.create(session_create)
    fetched = session_repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id


def test_list_returns_newest_first(session_repo: SessionRepository) -> None:
    first = session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1))
    second = session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=2))
    results = session_repo.list()
    assert [r.id for r in results][:2] == [second.id, first.id]


def test_list_filters_by_status(session_repo: SessionRepository) -> None:
    a = session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1))
    session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=2))
    session_repo.update_status(a.id, SessionStatus.INGESTING)

    results = session_repo.list(status=SessionStatus.INGESTING)
    assert [r.id for r in results] == [a.id]


def test_update_status_sets_completed_at_only_on_terminal_status(
    session_repo: SessionRepository, session_create: SessionCreate
) -> None:
    created = session_repo.create(session_create)

    still_running = session_repo.update_status(created.id, SessionStatus.INGESTING)
    assert still_running.completed_at is None

    terminal = session_repo.update_status(created.id, SessionStatus.FAILED, failure_reason="boom")
    assert terminal.completed_at is not None
    assert terminal.failure_reason == "boom"


def test_update_status_missing_session_raises(session_repo: SessionRepository) -> None:
    with pytest.raises(SessionNotFoundError):
        session_repo.update_status("does-not-exist", SessionStatus.FAILED)


def test_record_usage_accumulates(
    session_repo: SessionRepository, session_create: SessionCreate
) -> None:
    created = session_repo.create(session_create)
    session_repo.record_usage(
        created.id, input_tokens=100, output_tokens=50, cache_read_tokens=10, cost_usd=0.01
    )
    session_repo.record_usage(
        created.id, input_tokens=200, output_tokens=75, cache_read_tokens=20, cost_usd=0.02
    )
    fetched = session_repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.input_tokens == 300
    assert fetched.output_tokens == 125
    assert fetched.cache_read_tokens == 30
    assert fetched.estimated_cost_usd == pytest.approx(0.03)


def test_record_usage_missing_session_raises(session_repo: SessionRepository) -> None:
    with pytest.raises(SessionNotFoundError):
        session_repo.record_usage(
            "nope", input_tokens=1, output_tokens=1, cache_read_tokens=0, cost_usd=0.0
        )


def test_increment_fix_attempts(
    session_repo: SessionRepository, session_create: SessionCreate
) -> None:
    created = session_repo.create(session_create)
    assert session_repo.increment_fix_attempts(created.id) == 1
    assert session_repo.increment_fix_attempts(created.id) == 2


def test_increment_fix_attempts_missing_session_raises(session_repo: SessionRepository) -> None:
    with pytest.raises(SessionNotFoundError):
        session_repo.increment_fix_attempts("nope")
