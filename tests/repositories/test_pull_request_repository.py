import pytest

from devmind.repositories import PullRequestRepository, SessionRepository
from devmind.schemas.session import SessionCreate


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_create_and_get_by_session(
    pull_request_repo: PullRequestRepository, session_id: str
) -> None:
    created = pull_request_repo.create(
        session_id,
        number=42,
        url="https://github.com/a/b/pull/42",
        branch="devmind/issue-1-fix",
        head_sha="abc123",
    )
    fetched = pull_request_repo.get_by_session(session_id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.number == 42


def test_get_by_session_missing_returns_none(
    pull_request_repo: PullRequestRepository, session_id: str
) -> None:
    assert pull_request_repo.get_by_session(session_id) is None
