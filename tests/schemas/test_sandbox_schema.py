from __future__ import annotations

import pytest
from pydantic import ValidationError

from devmind.schemas.sandbox import CommandResult, SandboxCommand


def test_sandbox_command_requires_a_non_empty_argv() -> None:
    with pytest.raises(ValidationError):
        SandboxCommand(argv=())


def test_sandbox_command_defaults() -> None:
    cmd = SandboxCommand(argv=("pytest",))
    assert cmd.cwd is None
    assert cmd.timeout_seconds > 0
    assert cmd.env == {}


def test_sandbox_command_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValidationError):
        SandboxCommand(argv=("pytest",), timeout_seconds=0)


def test_command_result_succeeded_is_clean_exit_only() -> None:
    base = dict(argv=("x",), stdout="", stderr="", duration_seconds=1.0)
    assert CommandResult(exit_code=0, **base).succeeded is True
    assert CommandResult(exit_code=1, **base).succeeded is False
    assert CommandResult(exit_code=0, timed_out=True, **base).succeeded is False


def test_command_result_is_frozen() -> None:
    result = CommandResult(argv=("x",), exit_code=0, stdout="", stderr="", duration_seconds=1.0)
    with pytest.raises(ValidationError):
        result.exit_code = 2
