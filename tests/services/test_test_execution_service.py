"""`TestExecutionService` — argv assembly, targeted re-runs, persistence, events (E8-F1)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import PYTEST_EXECUTION_ARGS
from devmind.core.enums import EventType
from devmind.repositories import EventRepository, SessionRepository, TestRunRepository
from devmind.schemas.repo import RepoProfile
from devmind.schemas.session import SessionCreate
from devmind.services.pytest_output_parser import PytestOutputParser
from devmind.services.test_execution_service import TestExecutionService
from tests.fakes.fake_sandbox import FakeSandbox, command_result

_PROFILE = RepoProfile(
    language="python", test_command=("python", "-m", "pytest"), has_test_suite=True
)
_GREEN = command_result(stdout="..  [100%]\n2 passed in 0.10s\n")
_RED = command_result(
    exit_code=1,
    stdout=(
        "F  [100%]\n"
        "=================================== FAILURES ===================================\n"
        "_______________________________ test_add _______________________________\n"
        "tests/test_calc.py:4: in test_add\n"
        "    assert add(2, 2) == 4\n"
        "E   assert 0 == 4\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_calc.py::test_add - assert 0 == 4\n"
        "1 failed in 0.20s\n"
    ),
)


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def _service(
    db_session: SQLAlchemySession, sandbox: FakeSandbox, *, pytest_timeout_supported: bool = False
) -> TestExecutionService:
    return TestExecutionService(
        sandbox,
        PytestOutputParser(),
        TestRunRepository(db_session),
        EventRepository(db_session),
        pytest_timeout_supported=pytest_timeout_supported,
    )


async def test_argv_is_test_command_plus_execution_args(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    sandbox = FakeSandbox([_GREEN])
    await _service(db_session, sandbox).run(session_id, _PROFILE, attempt=1)
    assert sandbox.commands[-1].argv == ("python", "-m", "pytest", *PYTEST_EXECUTION_ARGS)


async def test_timeout_arg_added_only_when_supported(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    sandbox = FakeSandbox([_GREEN])
    await _service(db_session, sandbox, pytest_timeout_supported=True).run(
        session_id, _PROFILE, attempt=1
    )
    assert any(arg.startswith("--timeout=") for arg in sandbox.commands[-1].argv)


async def test_targeted_rerun_appends_node_ids_and_keyword(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    sandbox = FakeSandbox([_GREEN])
    await _service(db_session, sandbox).run(
        session_id,
        _PROFILE,
        attempt=2,
        node_ids=["tests/test_calc.py::test_add"],
        keyword="add",
    )
    argv = sandbox.commands[-1].argv
    assert "tests/test_calc.py::test_add" in argv
    assert argv[argv.index("-k") + 1] == "add"


async def test_run_persists_a_row_and_emits_a_test_run_event(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    sandbox = FakeSandbox([_RED])
    result = await _service(db_session, sandbox).run(session_id, _PROFILE, attempt=1)

    rows = TestRunRepository(db_session).list_for_session(session_id)
    assert len(rows) == 1
    assert rows[0].attempt == 1
    assert rows[0].is_baseline is False
    assert rows[0].failed == 1
    assert rows[0].signature == result.report.signature
    assert result.test_run_id == rows[0].id

    events = [
        e
        for e in EventRepository(db_session).list_since(session_id)
        if e.event_type is EventType.TEST_RUN
    ]
    assert len(events) == 1
    assert events[0].payload["attempt"] == 1
    assert events[0].payload["failed"] == 1
    assert events[0].payload["is_baseline"] is False


async def test_run_baseline_marks_the_row_and_uses_the_full_suite(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    sandbox = FakeSandbox([_RED])
    result = await _service(db_session, sandbox).run_baseline(session_id, _PROFILE)

    assert result.is_baseline is True
    assert result.attempt == 0
    # no node-id narrowing on a baseline run
    assert sandbox.commands[-1].argv == ("python", "-m", "pytest", *PYTEST_EXECUTION_ARGS)
    rows = TestRunRepository(db_session).list_for_session(session_id)
    assert rows[0].is_baseline is True


async def test_report_render_is_readable(db_session: SQLAlchemySession, session_id: str) -> None:
    sandbox = FakeSandbox([_RED])
    result = await _service(db_session, sandbox).run(session_id, _PROFILE, attempt=1)
    rendered = result.report.render()
    assert "tests/test_calc.py::test_add" in rendered
    assert "1 failed" in rendered
