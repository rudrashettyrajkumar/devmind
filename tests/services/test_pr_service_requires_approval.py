"""SI-3 at the E10 boundary: an unapproved session cannot open a PR, and performs
**zero** git operations — the guard is `open_draft_pr`'s first statement, so nothing
(no review build, no LLM call, no git) runs ahead of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import SessionStatus
from devmind.exceptions import ApprovalRequiredError
from tests.services._pr_kit import build_harness


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


async def test_unapproved_session_raises_and_runs_nothing(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    h = await build_harness(db_session, workspace, approve=False)

    with pytest.raises(ApprovalRequiredError):
        await h.service.open_draft_pr(h.session_id)

    assert h.runner.calls == []
    assert h.summary_llm.call_count == 0
    assert h.body_llm.call_count == 0
    assert h.prs.get_by_session(h.session_id) is None

    row = h.sessions.get_by_id(h.session_id)
    assert row is not None and row.status is SessionStatus.AWAITING_APPROVAL


async def test_rejected_session_cannot_open_a_pr(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    from devmind.core.enums import ApprovalDecision
    from devmind.repositories import ApprovalRepository, EventRepository, SessionRepository
    from devmind.services.approval_service import ApprovalService
    from devmind.services.session_state_machine import SessionStateMachine

    h = await build_harness(db_session, workspace, approve=False)
    machine = SessionStateMachine(SessionRepository(db_session), EventRepository(db_session))
    service = ApprovalService(
        ApprovalRepository(db_session),
        SessionRepository(db_session),
        machine,
        EventRepository(db_session),
    )
    await service.decide(
        h.session_id, ApprovalDecision.REJECTED, decided_by="Dana", reason="not this way"
    )

    with pytest.raises(ApprovalRequiredError):
        await h.service.open_draft_pr(h.session_id)
    assert h.runner.calls == []
