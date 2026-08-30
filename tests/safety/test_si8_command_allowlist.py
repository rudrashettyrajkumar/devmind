"""SI-8: shell execution is bounded and allowlisted.

  * `CommandAllowlist` rejects any binary outside `ALLOWED_COMMAND_BINARIES`, before
    anything runs;
  * no `shell=True` exists anywhere in the codebase (grep-asserted);
  * every `SandboxCommand` carries a positive timeout — the schema makes zero/negative
    impossible to construct.

A regression here is a broken invariant. Fix the code, never the test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from devmind.core.constants import ALLOWED_COMMAND_BINARIES
from devmind.exceptions import SandboxError
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.output_truncator import OutputTruncator
from devmind.services.subprocess_sandbox import SubprocessSandbox

_SRC = Path(__file__).resolve().parents[2] / "src" / "devmind"
_PY = Path(sys.executable).name


def test_si8_allowlist_blocks_unlisted_binaries() -> None:
    allowlist = CommandAllowlist()
    for binary in ("curl", "wget", "nc", "ssh", "bash", "node", "make"):
        with pytest.raises(SandboxError):
            allowlist.validate([binary, "--help"])


def test_si8_allowlist_default_set_has_no_network_tool() -> None:
    forbidden = {"curl", "wget", "nc", "ncat", "ssh", "scp", "telnet", "ftp"}
    assert forbidden.isdisjoint(ALLOWED_COMMAND_BINARIES)


async def test_si8_disallowed_binary_executes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = SubprocessSandbox(CommandAllowlist(), OutputTruncator(1_000))
    await sandbox.setup(workspace)
    with pytest.raises(SandboxError):
        await sandbox.run(SandboxCommand(argv=("curl", "http://x")))


def test_si8_no_shell_true_anywhere_in_the_source() -> None:
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        normalised = path.read_text(encoding="utf-8").lower().replace(" ", "")
        # Drop backtick-wrapped prose mentions ("never `shell=True`") in docstrings;
        # what must not exist is an actual `shell=True` keyword argument.
        code_only = normalised.replace("`shell=true`", "")
        if "shell=true" in code_only or "create_subprocess_shell" in code_only:
            offenders.append(str(path.relative_to(_SRC)))
    assert offenders == [], f"shell=True / create_subprocess_shell found in: {offenders}"


def test_si8_sandbox_command_cannot_carry_a_non_positive_timeout() -> None:
    for bad in (0, -1, -300):
        with pytest.raises(ValidationError):
            SandboxCommand(argv=("pytest",), timeout_seconds=bad)


def test_si8_sandbox_command_has_a_timeout_by_default() -> None:
    assert SandboxCommand(argv=("pytest",)).timeout_seconds > 0
