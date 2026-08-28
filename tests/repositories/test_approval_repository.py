import pytest

from devmind.core.enums import ApprovalDecision
from devmind.exceptions import RecordNotFoundError
from devmind.repositories import ApprovalRepository, SessionRepository
from devmind.schemas.session import SessionCreate


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_create_and_get_by_session(approval_repo: ApprovalRepository, session_id: str) -> None:
    created = approval_repo.create(session_id, token="tok-123")
    fetched = approval_repo.get_by_session(session_id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.decision is None
    assert fetched.consumed_at is None


def test_get_by_token(approval_repo: ApprovalRepository, session_id: str) -> None:
    approval_repo.create(session_id, token="tok-abc")
    fetched = approval_repo.get_by_token("tok-abc")
    assert fetched is not None
    assert fetched.session_id == session_id


def test_get_by_token_missing_returns_none(approval_repo: ApprovalRepository) -> None:
    assert approval_repo.get_by_token("nope") is None


def test_decide_records_decision(approval_repo: ApprovalRepository, session_id: str) -> None:
    approval_repo.create(session_id, token="tok-1")
    decided = approval_repo.decide(
        session_id, ApprovalDecision.APPROVED, decided_by="alice", reason=None
    )
    assert decided.decision is ApprovalDecision.APPROVED
    assert decided.decided_by == "alice"
    assert decided.decided_at is not None


def test_decide_missing_approval_raises(approval_repo: ApprovalRepository, session_id: str) -> None:
    with pytest.raises(RecordNotFoundError):
        approval_repo.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")


def test_consume_sets_consumed_at(approval_repo: ApprovalRepository, session_id: str) -> None:
    approval_repo.create(session_id, token="tok-1")
    approval_repo.decide(session_id, ApprovalDecision.APPROVED, decided_by="alice")
    consumed = approval_repo.consume(session_id)
    assert consumed.consumed_at is not None
