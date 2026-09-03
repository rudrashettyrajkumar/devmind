"""`GitService` — exact argv for branch / stage / commit / push, message format,
failure classification, and the no-force / dry-run guarantees (E10-F1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devmind.core.config import Settings
from devmind.core.enums import GitFailureReason
from devmind.exceptions import GitDeliveryError
from devmind.schemas.pull_request import CommitMessage
from devmind.services.git_service import GitService
from devmind.services.workspace_path_guard import WorkspacePathGuard
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output

_SHA = "1234567890abcdef1234567890abcdef12345678"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"anthropic_api_key": "sk-ant-test"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _service(workspace: Path, runner: FakeCommandRunner, **settings: object) -> GitService:
    return GitService(runner, WorkspacePathGuard(workspace), _settings(**settings))


@pytest.fixture
def message() -> CommitMessage:
    return CommitMessage(
        subject="fix: handle naive datetimes in parse_timestamp",
        body="It raised on naive input; it now assumes UTC.",
        issue_number=42,
        session_id="3f9a-session",
        approved_by="Dana Reviewer",
    )


async def test_create_branch_argv(workspace: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"]))
    branch = await _service(workspace, runner).create_branch(workspace, "devmind/issue-42-x")

    assert branch == "devmind/issue-42-x"
    assert runner.calls[0].argv == ["git", "switch", "-c", "devmind/issue-42-x"]
    assert runner.calls[0].cwd == workspace
    assert runner.calls[0].env.get("GIT_TERMINAL_PROMPT") == "0"


async def test_stage_all_argv(workspace: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"]))
    await _service(workspace, runner).stage_all(workspace)
    assert runner.calls[0].argv == ["git", "add", "-A"]


async def test_commit_argv_message_and_returned_sha(
    workspace: Path, message: CommitMessage
) -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("git", "rev-parse"): command_output(["git"], stdout=f"{_SHA}\n"),
            ("git", "commit"): command_output(["git"]),
        }
    )
    sha = await _service(workspace, runner).commit(workspace, message)

    assert sha == _SHA
    commit_call = runner.calls[0]
    assert commit_call.argv[:3] == ["git", "commit", "-m"]
    body = commit_call.argv[3]
    assert body.startswith("fix: handle naive datetimes in parse_timestamp\n\n")
    assert "Refs: #42" in body
    assert "Session: 3f9a-session" in body
    assert "Approved-by: Dana Reviewer" in body
    assert "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" in body
    assert runner.calls[1].argv == ["git", "rev-parse", "HEAD"]


async def test_commit_without_issue_number_has_no_refs_trailer(workspace: Path) -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("git", "rev-parse"): command_output(["git"], stdout=f"{_SHA}\n"),
            ("git", "commit"): command_output(["git"]),
        }
    )
    msg = CommitMessage(subject="fix: something", body="x", session_id="s", approved_by="Dana")
    await _service(workspace, runner).commit(workspace, msg)
    assert "Refs: #" not in runner.calls[0].argv[3]


async def test_push_argv_sets_upstream_and_never_forces(workspace: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"]))
    await _service(workspace, runner).push(workspace, "devmind/issue-42-x")

    argv = runner.calls[0].argv
    assert argv == ["git", "push", "--set-upstream", "origin", "devmind/issue-42-x"]
    assert "--force" not in argv
    assert "-f" not in argv
    assert not any(a.startswith("+") for a in argv)


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("! [rejected]        main -> main (non-fast-forward)", GitFailureReason.PUSH_REJECTED),
        ("remote: Permission to acme/widget.git denied", GitFailureReason.NO_PUSH_PERMISSION),
        ("fatal: a branch named 'x' already exists", GitFailureReason.REMOTE_BRANCH_EXISTS),
    ],
)
async def test_push_failures_are_classified(
    workspace: Path, stderr: str, reason: GitFailureReason
) -> None:
    runner = FakeCommandRunner(default=command_output(["git"], exit_code=1, stderr=stderr))
    with pytest.raises(GitDeliveryError) as excinfo:
        await _service(workspace, runner).push(workspace, "x")
    assert excinfo.value.reason is reason


async def test_branch_create_failure_raises(workspace: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"], exit_code=128, stderr="boom"))
    with pytest.raises(GitDeliveryError) as excinfo:
        await _service(workspace, runner).create_branch(workspace, "x")
    assert excinfo.value.reason is GitFailureReason.BRANCH_CREATE_FAILED


async def test_list_remote_branches_parses_ls_remote(workspace: Path) -> None:
    stdout = (
        "deadbeef\trefs/heads/main\n"
        "cafef00d\trefs/heads/devmind/issue-42-fix\n"
        "abc123\trefs/tags/v1.0\n"
    )
    runner = FakeCommandRunner(default=command_output(["git"], stdout=stdout))
    names = await _service(workspace, runner).list_remote_branches(workspace)

    assert names == frozenset({"main", "devmind/issue-42-fix"})
    assert runner.calls[0].argv == ["git", "ls-remote", "--heads", "origin"]


async def test_list_remote_branches_is_best_effort_on_failure(workspace: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"], exit_code=128, stderr="offline"))
    assert await _service(workspace, runner).list_remote_branches(workspace) == frozenset()


async def test_list_remote_branches_skips_the_remote_in_dry_run(workspace: Path) -> None:
    runner = FakeCommandRunner()  # any call raises
    svc = _service(workspace, runner, dry_run=True)
    assert await svc.list_remote_branches(workspace) == frozenset()
    assert runner.calls == []


async def test_dry_run_touches_no_runner(workspace: Path, message: CommitMessage) -> None:
    runner = FakeCommandRunner()  # no scripted output — any call raises
    svc = _service(workspace, runner, dry_run=True)

    assert await svc.create_branch(workspace, "devmind/x") == "devmind/x"
    await svc.stage_all(workspace)
    assert await svc.commit(workspace, message) == "0" * 40
    await svc.push(workspace, "devmind/x")

    assert runner.calls == []


async def test_workspace_outside_the_guard_root_is_refused(workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    runner = FakeCommandRunner(default=command_output(["git"]))
    with pytest.raises(GitDeliveryError):
        await _service(workspace, runner).create_branch(other, "x")
    assert runner.calls == []
