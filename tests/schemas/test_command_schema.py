from __future__ import annotations

import pytest
from pydantic import ValidationError

from devmind.schemas.command import CommandOutput


def test_ok_is_true_only_for_clean_exit() -> None:
    assert CommandOutput(argv=("git",), exit_code=0).ok is True


def test_ok_is_false_for_non_zero_exit() -> None:
    assert CommandOutput(argv=("git",), exit_code=1).ok is False


def test_ok_is_false_when_timed_out_even_with_zero_exit() -> None:
    assert CommandOutput(argv=("git",), exit_code=0, timed_out=True).ok is False


def test_is_frozen() -> None:
    out = CommandOutput(argv=("git",), exit_code=0)
    with pytest.raises(ValidationError):
        out.exit_code = 5
