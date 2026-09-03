"""`PRService.open_draft_pr` happy path — the full sequence, exact argv, `--draft`
always present, and the state / persistence / token effects (E10-F2-T1..T3, E10-F3-T2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, SessionStatus
from tests.services._pr_kit import HEAD_SHA, PR_URL, build_harness


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


async def test_open_draft_pr_full_sequence(db_session: SQLAlchemySession, workspace: Path) -> None:
    h = await build_harness(db_session, workspace)

    pr = await h.service.open_draft_pr(h.session_id)

    assert pr.number == 7
    assert pr.url == PR_URL
    assert pr.head_sha == HEAD_SHA
    assert pr.branch.startswith("devmind/issue-42-")
    assert pr.dry_run is False

    argvs = [c.argv for c in h.runner.calls]

    def first(pred) -> int:
        return next(i for i, a in enumerate(argvs) if pred(a))

    i_lsremote = first(lambda a: a == ["git", "ls-remote", "--heads", "origin"])
    i_switch = first(lambda a: a == ["git", "switch", "-c", pr.branch])
    i_add = first(lambda a: a == ["git", "add", "-A"])
    i_commit = first(lambda a: a[:3] == ["git", "commit", "-m"])
    i_revparse = first(lambda a: a == ["git", "rev-parse", "HEAD"])
    i_push = first(lambda a: a == ["git", "push", "--set-upstream", "origin", pr.branch])
    i_gh = first(lambda a: a[:4] == ["gh", "pr", "create", "--draft"])

    assert i_lsremote < i_switch < i_add < i_commit < i_revparse < i_push < i_gh
    assert argvs[i_gh][argvs[i_gh].index("--head") + 1] == pr.branch
    assert not any("--force" in a for a in argvs)


async def test_branch_name_avoids_a_collision_with_an_existing_remote_branch(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    from devmind.services.branch_namer import BranchNamer
    from tests.fakes.fake_command_runner import FakeCommandRunner, command_output
    from tests.services._pr_kit import HEAD_SHA as _SHA
    from tests.services._pr_kit import PR_URL as _URL

    default_branch = BranchNamer().build(42, "parse_timestamp rejects naive datetimes")

    runner = FakeCommandRunner(
        by_prefix={
            ("git", "ls-remote"): command_output(
                ["git"], stdout=f"sha\trefs/heads/{default_branch}\n"
            ),
            ("git", "rev-parse"): command_output(["git"], stdout=f"{_SHA}\n"),
            ("git",): command_output(["git"]),
            ("gh", "pr", "create"): command_output(["gh"], stdout=f"{_URL}\n"),
        }
    )
    h = await build_harness(db_session, workspace, runner=runner)
    pr = await h.service.open_draft_pr(h.session_id)

    assert pr.branch == f"{default_branch}-2"
    switch = next(c.argv for c in runner.calls if c.argv[:3] == ["git", "switch", "-c"])
    assert switch[3] == f"{default_branch}-2"


async def test_draft_flag_is_always_present(db_session: SQLAlchemySession, workspace: Path) -> None:
    h = await build_harness(db_session, workspace)
    await h.service.open_draft_pr(h.session_id)
    gh_argv = next(c.argv for c in h.runner.calls if c.argv[0] == "gh")
    assert "--draft" in gh_argv
    assert not any(a in gh_argv for a in ("merge", "--auto", "--merge"))


async def test_state_persistence_and_token_effects(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    h = await build_harness(db_session, workspace)
    pr = await h.service.open_draft_pr(h.session_id)

    row = h.sessions.get_by_id(h.session_id)
    assert row is not None and row.status is SessionStatus.PR_OPENED

    persisted = h.prs.get_by_session(h.session_id)
    assert persisted is not None
    assert persisted.number == pr.number
    assert persisted.branch == pr.branch
    assert persisted.head_sha == HEAD_SHA

    approval = h.approvals.get_by_session(h.session_id)
    assert approval is not None and approval.consumed_at is not None

    events = h.events.list_since(h.session_id)
    assert any(e.event_type is EventType.PR_OPENED for e in events)


async def test_commit_message_carries_the_approver_and_issue(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    h = await build_harness(db_session, workspace)
    await h.service.open_draft_pr(h.session_id)

    commit_argv = next(c.argv for c in h.runner.calls if c.argv[:3] == ["git", "commit", "-m"])
    message = commit_argv[3]
    assert "Approved-by: Dana Reviewer" in message
    assert "Refs: #42" in message
    assert f"Session: {h.session_id}" in message
    assert "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" in message


async def test_pr_body_has_every_mandatory_section_and_the_provenance_footer(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    h = await build_harness(db_session, workspace)
    await h.service.open_draft_pr(h.session_id)

    assert h.body_llm.call_count == 1
    body = h.runner.pr_bodies[0]
    for heading in (
        "## Summary",
        "## The issue",
        "## Changes",
        "## Test evidence",
        "## Risks and what to review closely",
        "## Provenance",
    ):
        assert heading in body
    assert "Dana Reviewer" in body
    assert "Model: claude-opus-5" in body
    assert "This PR is a draft and has not been merged." in body
    assert f"session `{h.session_id}`" in body
