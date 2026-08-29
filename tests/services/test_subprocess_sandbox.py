from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from devmind.core.constants import MAX_TEST_OUTPUT_CHARS
from devmind.exceptions import PathEscapeError, SandboxError
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.output_truncator import OutputTruncator
from devmind.services.subprocess_sandbox import SubprocessSandbox

_PY = sys.executable  # absolute path: no PATH lookup in the scrubbed env
_PY_NAME = Path(sys.executable).name  # basename, for the test allowlist


@pytest.fixture
def allowlist() -> CommandAllowlist:
    # sys.executable's basename may be "python3.12"; allow it plus the real binaries.
    return CommandAllowlist(frozenset({_PY_NAME, "python", "python3", "pytest", "sleep", "sh"}))


@pytest.fixture
async def sandbox(allowlist: CommandAllowlist, tmp_path: Path) -> SubprocessSandbox:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "pkg").mkdir()
    sb = SubprocessSandbox(allowlist, OutputTruncator(MAX_TEST_OUTPUT_CHARS))
    await sb.setup(workspace)
    return sb


async def test_run_before_setup_raises(allowlist: CommandAllowlist) -> None:
    sb = SubprocessSandbox(allowlist, OutputTruncator(100))
    with pytest.raises(SandboxError):
        await sb.run(SandboxCommand(argv=(_PY, "-c", "pass")))


async def test_successful_command(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(SandboxCommand(argv=(_PY, "-c", "print('hello')")))
    assert result.succeeded
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.duration_seconds >= 0


async def test_failing_command_captures_stderr(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"))
    )
    assert not result.succeeded
    assert result.exit_code == 2
    assert "boom" in result.stderr


async def test_timeout_kills_and_flags(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import time; time.sleep(30)"), timeout_seconds=1)
    )
    assert result.timed_out
    assert not result.succeeded


async def test_timeout_leaves_no_orphan_process(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    child.write_text(
        f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        f"import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}])\n"
        f"time.sleep(60)\n"
    )

    result = await sandbox.run(
        SandboxCommand(argv=(_PY, str(parent)), timeout_seconds=2),
    )
    assert result.timed_out

    for _ in range(30):
        if marker.exists():
            break
        await _sleep_ms(100)
    child_pid = int(marker.read_text().strip())

    for _ in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await _sleep_ms(100)
    else:  # pragma: no cover - only runs if the child never died
        os.kill(child_pid, signal.SIGKILL)
        pytest.fail("timeout left an orphan child process alive")


async def test_disallowed_binary_raises_and_runs_nothing(sandbox: SubprocessSandbox) -> None:
    with pytest.raises(SandboxError):
        await sandbox.run(SandboxCommand(argv=("curl", "https://example.com")))


async def test_cwd_inside_workspace_is_honoured(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        SandboxCommand(argv=(_PY, "-c", "import os; print(os.getcwd())"), cwd="pkg")
    )
    assert result.stdout.strip().endswith("/pkg")


async def test_cwd_outside_workspace_raises_path_escape(sandbox: SubprocessSandbox) -> None:
    with pytest.raises(PathEscapeError):
        await sandbox.run(SandboxCommand(argv=(_PY, "-c", "pass"), cwd="../.."))


async def test_environment_has_no_host_credentials(
    sandbox: SubprocessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    result = await sandbox.run(
        SandboxCommand(
            argv=(
                _PY,
                "-c",
                "import os,json; print(json.dumps(dict(os.environ)))",
            )
        )
    )
    child_env = json.loads(result.stdout)
    assert child_env.get("ANTHROPIC_API_KEY") == ""
    assert child_env.get("GITHUB_TOKEN") == ""
    assert "sk-ant-secret" not in result.stdout


async def test_huge_output_is_truncated_with_a_marker(
    allowlist: CommandAllowlist, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sb = SubprocessSandbox(allowlist, OutputTruncator(2_000))
    await sb.setup(workspace)
    result = await sb.run(
        SandboxCommand(argv=(_PY, "-c", "print('A'*5000); print('ZEND', end='')"))
    )
    assert result.truncated
    assert result.stdout.startswith("AAA")
    assert result.stdout.endswith("ZEND")
    assert "truncated" in result.stdout


async def test_install_dependencies_noop_when_profile_has_none(sandbox: SubprocessSandbox) -> None:
    profile = RepoProfile(language="python", install_command=None)
    result = await sandbox.install_dependencies(profile)
    assert result.succeeded
    assert result.argv == ()


async def test_install_dependencies_runs_the_profile_command(sandbox: SubprocessSandbox) -> None:
    profile = RepoProfile(language="python", install_command=(_PY, "-c", "print('deps installed')"))
    result = await sandbox.install_dependencies(profile)
    assert result.succeeded
    assert "deps installed" in result.stdout


async def test_start_failure_is_wrapped_in_sandbox_error(
    allowlist: CommandAllowlist, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # allow the basename but point argv[0] at a path that is not executable
    (workspace / "notexec").write_text("data")
    tight = CommandAllowlist(frozenset({"notexec"}))
    sb = SubprocessSandbox(tight, OutputTruncator(100))
    await sb.setup(workspace)
    with pytest.raises(SandboxError):
        await sb.run(SandboxCommand(argv=(str(workspace / "notexec"),)))


async def _sleep_ms(ms: int) -> None:
    await asyncio.sleep(ms / 1000)
