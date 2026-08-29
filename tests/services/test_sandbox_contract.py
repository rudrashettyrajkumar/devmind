"""The parametrised contract both `Sandbox` backends must satisfy (E5-F3-T1).

Every assertion runs against `SubprocessSandbox` for real; the `DockerSandbox`
parameter skips with a stated reason when no daemon is reachable (the primary dev box
has none). A skipped backend is never reported as a passing one.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from devmind.core.enums import SandboxBackend
from devmind.exceptions import PathEscapeError, SandboxError
from devmind.interfaces.sandbox import Sandbox
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.docker_sandbox import DockerSandbox
from devmind.services.output_truncator import OutputTruncator
from devmind.services.sandbox_factory import SandboxFactory
from devmind.services.subprocess_sandbox import SubprocessSandbox

_PY = sys.executable  # absolute path: no PATH lookup in the scrubbed env
_PY_NAME = Path(sys.executable).name  # basename, for the test allowlist
_CONTRACT_ALLOWLIST = CommandAllowlist(
    frozenset({_PY_NAME, "python", "python3", "sh", "sleep", "echo", "printf"})
)
_DOCKER_IMAGE = "python:3.12-slim"


def _docker_available() -> bool:
    return SandboxFactory._docker_reachable()


@pytest.fixture(params=[SandboxBackend.SUBPROCESS, SandboxBackend.DOCKER])
async def sandbox(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Sandbox]:
    backend = request.param
    workspace = tmp_path / "ws"
    (workspace / "sub").mkdir(parents=True)

    sb: Sandbox
    if backend is SandboxBackend.DOCKER:
        if not _docker_available():
            pytest.skip("docker daemon unavailable")
        import docker

        sb = DockerSandbox(
            client=docker.from_env(),
            image=_DOCKER_IMAGE,
            allowlist=_CONTRACT_ALLOWLIST,
            truncator=OutputTruncator(2_000),
        )
    else:
        sb = SubprocessSandbox(_CONTRACT_ALLOWLIST, OutputTruncator(2_000))

    await sb.setup(workspace)
    try:
        yield sb
    finally:
        await sb.teardown()


async def test_success_exit_zero_and_stdout(sandbox: Sandbox) -> None:
    result = await sandbox.run(SandboxCommand(argv=(_PY, "-c", "print('hello')")))
    assert result.exit_code == 0
    assert "hello" in result.stdout


async def test_failure_nonzero_exit_and_stderr(sandbox: Sandbox) -> None:
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import sys; sys.stderr.write('nope'); sys.exit(1)"))
    )
    assert result.exit_code != 0
    assert "nope" in result.stderr


async def test_timeout_is_flagged_and_killed_quickly(sandbox: Sandbox) -> None:
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import time; time.sleep(30)"), timeout_seconds=1)
    )
    assert result.timed_out
    assert result.duration_seconds < 15


async def test_huge_output_is_truncated_head_and_tail(sandbox: Sandbox) -> None:
    script = "print('HEAD' + 'x' * 50000); print('TAIL', end='')"
    result = await sandbox.run(SandboxCommand(argv=(_PY, "-c", script)))
    assert result.truncated
    assert result.stdout.startswith("HEAD")
    assert result.stdout.rstrip().endswith("TAIL")
    assert "truncated" in result.stdout


async def test_disallowed_binary_raises_and_runs_nothing(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxError):
        await sandbox.run(SandboxCommand(argv=("curl", "http://example.com")))


async def test_cwd_outside_workspace_raises(sandbox: Sandbox) -> None:
    with pytest.raises(PathEscapeError):
        await sandbox.run(SandboxCommand(argv=(_PY, "-c", "pass"), cwd="../../.."))


async def test_environment_carries_no_host_tokens(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_leak")
    result = await sandbox.run(
        SandboxCommand(
            argv=(
                _PY,
                "-c",
                "import os; print('\\n'.join(f'{k}={v}' for k,v in os.environ.items()))",
            )
        )
    )
    assert "sk-ant-leak" not in result.stdout
    assert "ghp_leak" not in result.stdout


async def test_network_egress(sandbox: Sandbox) -> None:
    script = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3).close()\n"
        "    print('NETWORK_OK')\n"
        "except OSError as exc:\n"
        "    print(f'NETWORK_BLOCKED {exc}')\n"
    )
    result = await sandbox.run(SandboxCommand(argv=(_PY, "-c", script), timeout_seconds=10))
    if isinstance(sandbox, DockerSandbox):
        assert "NETWORK_BLOCKED" in result.stdout  # kernel-enforced --network=none
    else:
        # Subprocess isolation is not a network boundary — documented gap (SI-2 §7).
        assert "NETWORK_OK" in result.stdout or "NETWORK_BLOCKED" in result.stdout
