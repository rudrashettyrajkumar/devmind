from __future__ import annotations

import sys
from pathlib import Path

import pytest

from devmind.core.constants import COMMAND_NOT_FOUND_EXIT_CODE
from devmind.services.subprocess_command_runner import SubprocessCommandRunner


@pytest.fixture
def runner() -> SubprocessCommandRunner:
    return SubprocessCommandRunner(default_timeout=10)


async def test_captures_stdout_and_zero_exit(runner: SubprocessCommandRunner) -> None:
    result = await runner.run([sys.executable, "-c", "print('hello')"])
    assert result.ok
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


async def test_non_zero_exit_is_reported_not_raised(runner: SubprocessCommandRunner) -> None:
    result = await runner.run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert not result.ok
    assert result.exit_code == 3


async def test_missing_binary_returns_command_not_found(runner: SubprocessCommandRunner) -> None:
    result = await runner.run(["devmind-no-such-binary-xyz"])
    assert result.exit_code == COMMAND_NOT_FOUND_EXIT_CODE
    assert "command not found" in result.stderr


async def test_timeout_kills_and_flags(runner: SubprocessCommandRunner) -> None:
    result = await runner.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert result.timed_out
    assert not result.ok


async def test_cwd_is_honoured(runner: SubprocessCommandRunner, tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here")
    result = await runner.run(
        [sys.executable, "-c", "import os; print(sorted(os.listdir('.')))"], cwd=tmp_path
    )
    assert "marker.txt" in result.stdout


async def test_env_overrides_are_applied(runner: SubprocessCommandRunner) -> None:
    result = await runner.run(
        [sys.executable, "-c", "import os; print(os.environ.get('DEVMIND_X'))"],
        env={"DEVMIND_X": "yes"},
    )
    assert result.stdout.strip() == "yes"


async def test_non_interactive_git_env_is_forced(runner: SubprocessCommandRunner) -> None:
    result = await runner.run(
        [sys.executable, "-c", "import os; print(os.environ['GIT_TERMINAL_PROMPT'])"]
    )
    assert result.stdout.strip() == "0"


async def test_empty_argv_raises(runner: SubprocessCommandRunner) -> None:
    with pytest.raises(ValueError):
        await runner.run([])
