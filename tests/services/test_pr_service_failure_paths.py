"""E10-F2-T4: every delivery failure moves the session to `FAILED`, keeps the work,
and is never retried against the remote. The approval token is not consumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, GitFailureReason, SessionStatus
from devmind.exceptions import GitDeliveryError
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output
from tests.services._pr_kit import HEAD_SHA, PR_URL, build_harness


def _runner(*, push=None, gh=None) -> FakeCommandRunner:
    push = push or command_output(["git"])
    gh = gh or command_output(["gh"], stdout=f"{PR_URL}\n")
    return FakeCommandRunner(
        by_prefix={
            ("git", "push"): push,
            ("git", "rev-parse"): command_output(["git"], stdout=f"{HEAD_SHA}\n"),
            ("git",): command_output(["git"]),
            ("gh", "pr", "create"): gh,
        }
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.mark.parametrize(
    ("push_stderr", "reason"),
    [
        ("! [rejected] (non-fast-forward)", GitFailureReason.PUSH_REJECTED),
        (
            "remote: Permission to acme/widget.git denied to bot",
            GitFailureReason.NO_PUSH_PERMISSION,
        ),
        (
            "fatal: a branch named 'x' already exists on the remote",
            GitFailureReason.REMOTE_BRANCH_EXISTS,
        ),
    ],
)
async def test_push_failure_marks_session_failed(
    db_session: SQLAlchemySession, workspace: Path, push_stderr: str, reason: GitFailureReason
) -> None:
    runner = _runner(push=command_output(["git"], exit_code=1, stderr=push_stderr))
    h = await build_harness(db_session, workspace, runner=runner)

    with pytest.raises(GitDeliveryError) as excinfo:
        await h.service.open_draft_pr(h.session_id)
    assert excinfo.value.reason is reason

    row = h.sessions.get_by_id(h.session_id)
    assert row is not None and row.status is SessionStatus.FAILED
    assert row.failure_reason and reason.value in _event_reasons(h)

    assert h.prs.get_by_session(h.session_id) is None
    approval = h.approvals.get_by_session(h.session_id)
    assert approval is not None and approval.consumed_at is None

    # no force-push was attempted as a recovery
    assert not any("--force" in c.argv for c in runner.calls)
    push_calls = [c for c in runner.calls if c.argv[:2] == ["git", "push"]]
    assert len(push_calls) == 1


async def test_gh_pr_create_failure_marks_session_failed_with_branch_pushed(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    runner = _runner(gh=command_output(["gh"], exit_code=1, stderr="server error 500"))
    h = await build_harness(db_session, workspace, runner=runner)

    with pytest.raises(GitDeliveryError) as excinfo:
        await h.service.open_draft_pr(h.session_id)
    assert excinfo.value.reason is GitFailureReason.PR_CREATE_FAILED

    row = h.sessions.get_by_id(h.session_id)
    assert row is not None and row.status is SessionStatus.FAILED
    # the branch really was pushed before gh failed
    assert any(c.argv[:2] == ["git", "push"] for c in runner.calls)
    assert h.prs.get_by_session(h.session_id) is None
    approval = h.approvals.get_by_session(h.session_id)
    assert approval is not None and approval.consumed_at is None


def _event_reasons(h) -> str:
    events = h.events.list_since(h.session_id)
    failed = [e for e in events if e.event_type is EventType.SESSION_FAILED]
    return " ".join(str(e.payload) for e in failed)
