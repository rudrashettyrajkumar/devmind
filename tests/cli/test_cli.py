"""`DevMindCLI` + `main` — command parsing, and `approve` refusing without the
typed confirmation (E11-F3-T "test_cli").
"""

from __future__ import annotations

import json

import httpx
import pytest
from rich.console import Console

from devmind.cli.client import CLIError, DevMindCLI
from devmind.cli.main import build_parser, main


class _Recorder:
    """Captures every request the CLI makes and replies from a scripted table."""

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self._routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        payload = self._routes.get((request.method, request.url.path), {})
        return httpx.Response(200, json=payload)


def _cli(recorder: _Recorder, *, confirm: str = "") -> DevMindCLI:
    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    return DevMindCLI(
        client, console=Console(quiet=True), confirm=lambda _prompt: confirm, sleep=lambda _s: None
    )


# --- parsing -------------------------------------------------------------


def test_parser_reads_run_arguments() -> None:
    args = build_parser().parse_args(["run", "https://github.com/a/b", "42"])
    assert args.command == "run"
    assert args.repo == "https://github.com/a/b"
    assert args.issue == 42


def test_parser_requires_by_for_approve() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["approve", "sid-1"])


def test_parser_requires_reason_for_reject() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reject", "sid-1", "--by", "Dana"])
    ok = build_parser().parse_args(["reject", "sid-1", "--by", "Dana", "--reason", "no"])
    assert ok.reason == "no"


# --- approve confirmation ---------------------------------------------


def test_approve_refuses_without_a_matching_confirmation() -> None:
    recorder = _Recorder({})
    cli = _cli(recorder, confirm="not-the-id")

    with pytest.raises(CLIError):
        cli.approve("sid-123", "Dana")

    assert recorder.calls == []  # nothing was POSTed


def test_approve_posts_when_the_confirmation_matches() -> None:
    recorder = _Recorder({("POST", "/api/v1/sessions/sid-123/approval"): {"decision": "approved"}})
    cli = _cli(recorder, confirm="sid-123")

    cli.approve("sid-123", "Dana")

    method, path, body = recorder.calls[0]
    assert (method, path) == ("POST", "/api/v1/sessions/sid-123/approval")
    assert body == {"decision": "approved", "decided_by": "Dana"}


def test_run_posts_and_returns_the_new_id() -> None:
    recorder = _Recorder({("POST", "/api/v1/sessions"): {"id": "sid-new", "status": "created"}})
    cli = _cli(recorder)

    session_id = cli.run("https://github.com/a/b", 7)

    assert session_id == "sid-new"
    assert recorder.calls[0][2] == {"repo_url": "https://github.com/a/b", "issue_number": 7}


def test_reject_sends_the_reason() -> None:
    recorder = _Recorder({("POST", "/api/v1/sessions/s/approval"): {"decision": "rejected"}})
    _cli(recorder).reject("s", "Dana", "not this way")
    assert recorder.calls[0][2] == {
        "decision": "rejected",
        "decided_by": "Dana",
        "reason": "not this way",
    }


def test_cli_error_surfaces_a_4xx_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "already decided"})

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    cli = DevMindCLI(client, console=Console(quiet=True), confirm=lambda _p: "s")
    with pytest.raises(CLIError, match="already decided"):
        cli.approve("s", "Dana")


def test_main_dispatches_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    real_client = httpx.Client

    def fake_client(*_args: object, **_kwargs: object) -> httpx.Client:
        return real_client(
            base_url="http://test",
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, json={"id": "sid-x", "status": "created"})
            ),
        )

    monkeypatch.setattr("devmind.cli.main.httpx.Client", fake_client)
    monkeypatch.setattr(
        "devmind.cli.client.DevMindCLI.run",
        lambda self, repo, issue: seen.update(repo=repo, issue=issue),
    )

    code = main(["run", "https://github.com/a/b", "9"])
    assert code == 0
    assert seen == {"repo": "https://github.com/a/b", "issue": 9}
