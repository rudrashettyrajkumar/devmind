"""SI-2: remote operations are impossible from inside the agent's execution context.

Two mechanisms, one test file each side:
  * the sandbox environment carries none of the operator's credentials, and git is
    forced non-interactive, so repo code cannot authenticate to a remote;
  * `DockerSandbox` runs its session container with `network_mode="none"` — network
    isolation the kernel enforces, not a policy anything can opt out of.

A regression here is a broken invariant. Fix the code, never the test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from devmind.core.constants import SANDBOX_FORBIDDEN_ENV_FRAGMENTS
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.docker_sandbox import DockerSandbox
from devmind.services.output_truncator import OutputTruncator
from devmind.services.sandbox_environment import SandboxEnvironment
from devmind.services.subprocess_sandbox import SubprocessSandbox

_PY = sys.executable
_PY_NAME = Path(sys.executable).name


def test_si2_sandbox_environment_blanks_every_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_real")
    monkeypatch.setenv("GH_TOKEN", "gh_real")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-real")

    env = SandboxEnvironment().build()

    for name, value in env.items():
        if any(fragment in name.upper() for fragment in SANDBOX_FORBIDDEN_ENV_FRAGMENTS):
            assert value == ""
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "/bin/false"


async def test_si2_no_token_reaches_a_real_child_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-appear")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = SubprocessSandbox(
        CommandAllowlist(frozenset({_PY_NAME, "python", "python3"})),
        OutputTruncator(10_000),
    )
    await sandbox.setup(workspace)
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import os; print(''.join(os.environ.values()))"))
    )
    assert "sk-ant-should-not-appear" not in result.stdout


async def test_si2_docker_session_container_has_no_network(tmp_path: Path) -> None:
    created: list[dict[str, Any]] = []

    class _Container:
        short_id = "x"

        def start(self) -> None: ...
        def remove(self, *, force: bool = False) -> None: ...

    class _Containers:
        def create(self, image: str, **kwargs: Any) -> _Container:
            created.append(kwargs)
            return _Container()

    class _Client:
        containers = _Containers()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = DockerSandbox(_Client(), "img", CommandAllowlist(), OutputTruncator(100))
    await sandbox.setup(workspace)

    assert created and created[0]["network_mode"] == "none"
