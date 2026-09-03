"""E10-F3-T3: `settings.dry_run` makes the whole delivery path demonstrable with no
remote — no git/gh argv executed, a synthetic result returned, nothing persisted or
transitioned, the approval token left unspent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import SessionStatus
from tests.fakes.fake_command_runner import FakeCommandRunner
from tests.services._pr_kit import build_harness


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


async def test_dry_run_executes_no_remote_and_persists_nothing(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    # a runner with no scripted output — any .run() call would raise AssertionError
    runner = FakeCommandRunner()
    h = await build_harness(db_session, workspace, runner=runner, dry_run=True)

    pr = await h.service.open_draft_pr(h.session_id)

    assert pr.dry_run is True
    assert pr.number == 0
    assert "DRY-RUN" in pr.url
    assert pr.branch.startswith("devmind/issue-42-")
    assert pr.head_sha == "0" * 40

    assert runner.calls == []
    assert h.prs.get_by_session(h.session_id) is None

    row = h.sessions.get_by_id(h.session_id)
    assert row is not None and row.status is SessionStatus.APPROVED

    approval = h.approvals.get_by_session(h.session_id)
    assert approval is not None and approval.consumed_at is None
