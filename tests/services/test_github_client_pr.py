"""`GitHubClient.create_draft_pr` — exact argv, `--draft` always present, URL/number
parsing, failure handling, and dry-run (E10-F2).
"""

from __future__ import annotations

import pytest

from devmind.core.enums import GitFailureReason
from devmind.exceptions import GitDeliveryError
from devmind.services.github_client import GitHubClient
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output

_PR_URL = "https://github.com/acme/widget/pull/7"


async def test_create_draft_pr_argv_and_result() -> None:
    runner = FakeCommandRunner(
        by_prefix={("gh", "pr", "create"): command_output(["gh"], stdout=f"{_PR_URL}\n")}
    )
    client = GitHubClient(runner, token="secret-token")

    pr = await client.create_draft_pr(
        "https://github.com/acme/widget",
        base="main",
        head="devmind/issue-7-fix",
        title="fix: widget crash",
        body="## Summary\n\nbody text",
    )

    assert pr.number == 7
    assert pr.url == _PR_URL
    argv = runner.calls[0].argv
    assert argv[:4] == ["gh", "pr", "create", "--draft"]
    assert "--repo" in argv and "acme/widget" in argv
    assert argv[argv.index("--base") + 1] == "main"
    assert argv[argv.index("--head") + 1] == "devmind/issue-7-fix"
    assert argv[argv.index("--title") + 1] == "fix: widget crash"
    assert "--body-file" in argv
    assert "merge" not in argv and "--auto" not in argv
    assert runner.calls[0].env == {"GH_TOKEN": "secret-token"}


async def test_body_file_is_removed_after_the_call() -> None:
    captured: dict[str, str] = {}

    class _Recorder(FakeCommandRunner):
        async def run(self, argv, **kw):  # type: ignore[no-untyped-def, override]
            path = argv[argv.index("--body-file") + 1]
            captured["path"] = path
            captured["contents"] = open(path, encoding="utf-8").read()  # noqa: SIM115
            return await super().run(argv, **kw)

    runner = _Recorder(
        by_prefix={("gh", "pr", "create"): command_output(["gh"], stdout=f"{_PR_URL}\n")}
    )
    client = GitHubClient(runner, token=None)
    await client.create_draft_pr(
        "https://github.com/acme/widget",
        base="main",
        head="h",
        title="t",
        body="the pr body",
    )

    from pathlib import Path

    assert captured["contents"] == "the pr body"
    assert not Path(captured["path"]).exists()


async def test_gh_failure_raises_git_delivery_error() -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("gh", "pr", "create"): command_output(
                ["gh"], exit_code=1, stderr="pull request already exists for branch"
            )
        }
    )
    client = GitHubClient(runner, token=None)
    with pytest.raises(GitDeliveryError) as excinfo:
        await client.create_draft_pr(
            "https://github.com/acme/widget", base="main", head="h", title="t", body="b"
        )
    assert excinfo.value.reason is GitFailureReason.PR_CREATE_FAILED
    assert "was pushed and is" in str(excinfo.value)


async def test_unparseable_output_raises() -> None:
    runner = FakeCommandRunner(
        by_prefix={("gh", "pr", "create"): command_output(["gh"], stdout="done, no url here")}
    )
    client = GitHubClient(runner, token=None)
    with pytest.raises(GitDeliveryError):
        await client.create_draft_pr(
            "https://github.com/acme/widget", base="main", head="h", title="t", body="b"
        )


async def test_dry_run_executes_nothing() -> None:
    runner = FakeCommandRunner()  # any .run() raises
    client = GitHubClient(runner, token=None)

    pr = await client.create_draft_pr(
        "https://github.com/acme/widget",
        base="main",
        head="h",
        title="t",
        body="b",
        dry_run=True,
    )
    assert pr.number == 0
    assert "DRY-RUN" in pr.url
    assert runner.calls == []
