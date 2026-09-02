import pytest

from devmind.repositories import SessionRepository, TestRunRepository
from devmind.schemas.session import SessionCreate


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_create_and_read_back(test_run_repo: TestRunRepository, session_id: str) -> None:
    created = test_run_repo.create(
        session_id,
        attempt=1,
        is_baseline=False,
        exit_code=1,
        passed=10,
        failed=2,
        errors=0,
        signature="abc123",
        report={"failures": ["test_a", "test_b"]},
        duration_seconds=3.5,
    )
    assert created.signature == "abc123"
    assert created.report == {"failures": ["test_a", "test_b"]}


def test_list_for_session_orders_by_creation(
    test_run_repo: TestRunRepository, session_id: str
) -> None:
    for attempt in range(1, 4):
        test_run_repo.create(
            session_id,
            attempt=attempt,
            is_baseline=False,
            exit_code=1,
            passed=0,
            failed=1,
            errors=0,
            signature=f"sig-{attempt}",
            report={},
            duration_seconds=1.0,
        )
    runs = test_run_repo.list_for_session(session_id)
    assert [r.attempt for r in runs] == [1, 2, 3]


def test_latest_for_session(test_run_repo: TestRunRepository, session_id: str) -> None:
    for attempt in range(1, 4):
        test_run_repo.create(
            session_id,
            attempt=attempt,
            is_baseline=False,
            exit_code=0,
            passed=1,
            failed=0,
            errors=0,
            signature=None,
            report={},
            duration_seconds=1.0,
        )
    latest = test_run_repo.latest_for_session(session_id)
    assert latest is not None
    assert latest.attempt == 3


def test_latest_for_session_none_when_no_runs(
    test_run_repo: TestRunRepository, session_id: str
) -> None:
    assert test_run_repo.latest_for_session(session_id) is None


def _create(repo: TestRunRepository, session_id: str, *, attempt: int, is_baseline: bool) -> None:
    repo.create(
        session_id,
        attempt=attempt,
        is_baseline=is_baseline,
        exit_code=1,
        passed=0,
        failed=1,
        errors=0,
        signature=f"sig-{'base' if is_baseline else attempt}",
        report={},
        duration_seconds=1.0,
    )


def test_baseline_for_session(test_run_repo: TestRunRepository, session_id: str) -> None:
    assert test_run_repo.baseline_for_session(session_id) is None
    _create(test_run_repo, session_id, attempt=0, is_baseline=True)
    _create(test_run_repo, session_id, attempt=1, is_baseline=False)
    baseline = test_run_repo.baseline_for_session(session_id)
    assert baseline is not None
    assert baseline.is_baseline is True
    assert baseline.signature == "sig-base"


def test_attempts_for_session_excludes_the_baseline_and_orders_oldest_first(
    test_run_repo: TestRunRepository, session_id: str
) -> None:
    _create(test_run_repo, session_id, attempt=0, is_baseline=True)
    for attempt in (1, 2, 3):
        _create(test_run_repo, session_id, attempt=attempt, is_baseline=False)
    attempts = test_run_repo.attempts_for_session(session_id)
    assert [r.attempt for r in attempts] == [1, 2, 3]
    assert all(r.is_baseline is False for r in attempts)
