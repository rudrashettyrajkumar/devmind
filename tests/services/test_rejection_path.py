"""The rejection path — a human says no and the system stops cleanly (E9-F2-T3).

`REJECTED` is persisted with its reason, `completed_at` is set, the workspace is
left on disk for inspection, an `APPROVAL_DECIDED` event is written, and nothing is
pushed — there is no retry and no fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import ApprovalDecision, EventType, SessionStatus
from devmind.exceptions import ApprovalRequiredError
from devmind.repositories import (
    ApprovalRepository,
    EventRepository,
    PullRequestRepository,
    SessionRepository,
)
from devmind.schemas.session import SessionCreate
from devmind.services.approval_service import ApprovalService
from devmind.services.remote_operation_guard import RemoteOperationGuard
from devmind.services.session_state_machine import SessionStateMachine

_TO_SUMMARIZING = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "patch.py").write_text("# the agent's work, retained for inspection\n")
    return ws


async def test_rejection_persists_reason_retains_workspace_and_pushes_nothing(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    machine = SessionStateMachine(sessions, events)
    service = ApprovalService(ApprovalRepository(db_session), sessions, machine, events)

    model = sessions.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=9))
    sessions.record_ingestion(
        model.id,
        base_commit_sha="s",
        default_branch="main",
        workspace_path=str(workspace),
        has_test_suite=True,
    )
    for step in _TO_SUMMARIZING:
        machine.transition(model.id, step)

    await service.request(model.id)
    record = await service.decide(
        model.id, ApprovalDecision.REJECTED, decided_by="carol", reason="wrong approach"
    )

    row = sessions.get_by_id(model.id)
    assert row is not None
    assert row.status is SessionStatus.REJECTED
    assert row.completed_at is not None
    assert record.reason == "wrong approach"

    assert workspace.exists() and (workspace / "patch.py").exists()

    decided = [e for e in events.list_since(model.id) if e.event_type is EventType.APPROVAL_DECIDED]
    assert decided and decided[0].payload["decision"] == "rejected"

    assert PullRequestRepository(db_session).get_by_session(model.id) is None

    guard = RemoteOperationGuard(service)
    with pytest.raises(ApprovalRequiredError):
        await guard.authorize(model.id, "open_draft_pr")


async def test_rejected_session_cannot_be_decided_again(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    machine = SessionStateMachine(sessions, events)
    service = ApprovalService(ApprovalRepository(db_session), sessions, machine, events)

    model = sessions.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=9))
    for step in _TO_SUMMARIZING:
        machine.transition(model.id, step)
    await service.request(model.id)
    await service.decide(model.id, ApprovalDecision.REJECTED, decided_by="carol", reason="no")

    from devmind.exceptions import ApprovalDecisionError

    with pytest.raises(ApprovalDecisionError):
        await service.decide(model.id, ApprovalDecision.APPROVED, decided_by="carol")
