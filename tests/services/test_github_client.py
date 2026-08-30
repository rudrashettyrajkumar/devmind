from __future__ import annotations

import json

import pytest

from devmind.core.enums import IssueState
from devmind.exceptions import GitHubError
from devmind.services.github_client import GitHubClient
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output

_ISSUE_JSON = json.dumps(
    {
        "number": 7,
        "title": "Widget crashes on empty input",
        "body": "Steps to reproduce...",
        "labels": [{"name": "bug"}, {"name": "priority:high"}],
        "state": "OPEN",
    }
)


async def test_fetch_issue_parses_gh_json() -> None:
    runner = FakeCommandRunner(
        by_prefix={("gh", "issue", "view"): command_output(["gh"], stdout=_ISSUE_JSON)}
    )
    client = GitHubClient(runner, token=None)

    issue = await client.fetch_issue("https://github.com/acme/widget", 7)

    assert issue.number == 7
    assert issue.title == "Widget crashes on empty input"
    assert issue.labels == ("bug", "priority:high")
    assert issue.state is IssueState.OPEN


async def test_fetch_issue_builds_the_expected_argv() -> None:
    runner = FakeCommandRunner(by_prefix={("gh",): command_output(["gh"], stdout=_ISSUE_JSON)})
    client = GitHubClient(runner, token="secret-token")

    await client.fetch_issue("git@github.com:acme/widget.git", 7)

    call = runner.calls[0]
    assert call.argv[:5] == ["gh", "issue", "view", "7", "--repo"]
    assert "acme/widget" in call.argv
    assert "number,title,body,labels,state" in call.argv
    assert call.env.get("GH_TOKEN") == "secret-token"


async def test_missing_issue_raises_github_error() -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("gh",): command_output(
                ["gh"], exit_code=1, stderr="could not find any issue named 999"
            )
        }
    )
    client = GitHubClient(runner, token=None)

    with pytest.raises(GitHubError) as excinfo:
        await client.fetch_issue("https://github.com/acme/widget", 999)
    assert "could not find any issue" in str(excinfo.value)


async def test_unparseable_json_raises_github_error() -> None:
    runner = FakeCommandRunner(by_prefix={("gh",): command_output(["gh"], stdout="not json")})
    client = GitHubClient(runner, token=None)
    with pytest.raises(GitHubError):
        await client.fetch_issue("https://github.com/acme/widget", 1)


async def test_bad_repo_url_raises_before_running_anything() -> None:
    runner = FakeCommandRunner()
    client = GitHubClient(runner, token=None)
    with pytest.raises(GitHubError):
        await client.fetch_issue("not-a-url", 1)
    assert runner.calls == []
