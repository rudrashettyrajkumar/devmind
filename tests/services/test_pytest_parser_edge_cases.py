"""`PytestOutputParser` on the runs with no pytest summary at all (E8-F2-T4).

A killed run produces no summary, and garbage output produces no summary. A parser
that returned "0 failures" for either would convince `SelfCorrectionController` the
suite passed. The single invariant these tests protect: **neither reports success.**
"""

from __future__ import annotations

import pytest

from devmind.schemas.sandbox import CommandResult
from devmind.services.pytest_output_parser import PytestOutputParser


@pytest.fixture
def parser() -> PytestOutputParser:
    return PytestOutputParser()


def test_timeout_never_reports_success(parser: PytestOutputParser) -> None:
    result = CommandResult(
        argv=("python", "-m", "pytest"),
        exit_code=-9,
        stdout="collecting ... \ntests/test_slow.py ",
        stderr="",
        duration_seconds=300.0,
        timed_out=True,
    )
    report = parser.parse(result)
    assert report.timed_out is True
    assert report.succeeded is False
    assert report.signature != ""


def test_unparseable_garbage_never_reports_success(parser: PytestOutputParser) -> None:
    result = CommandResult(
        argv=("python", "-m", "pytest"),
        exit_code=1,
        stdout="Traceback (most recent call last):\n  File ...\nImportError: libpython missing",
        stderr="Segmentation fault (core dumped)",
        duration_seconds=0.4,
    )
    report = parser.parse(result)
    assert report.unparseable is True
    assert report.succeeded is False


def test_empty_output_with_zero_exit_is_still_not_a_pass(parser: PytestOutputParser) -> None:
    # A clean exit code with nothing that looks like pytest — never fabricate a pass.
    result = CommandResult(
        argv=("python", "-m", "pytest"),
        exit_code=0,
        stdout="",
        stderr="",
        duration_seconds=0.0,
    )
    report = parser.parse(result)
    assert report.unparseable is True
    assert report.succeeded is False


def test_timeout_and_unparseable_have_distinct_signatures(parser: PytestOutputParser) -> None:
    timed_out = parser.parse(
        CommandResult(
            argv=("pytest",),
            exit_code=-9,
            stdout="",
            stderr="",
            duration_seconds=1.0,
            timed_out=True,
        )
    )
    garbage = parser.parse(
        CommandResult(argv=("pytest",), exit_code=2, stdout="boom", stderr="", duration_seconds=1.0)
    )
    assert timed_out.signature != garbage.signature
