"""Baseline discipline (E8-F1-T2) — failures already red on the clean checkout are
recorded and then excluded from every later verdict. The agent is neither blamed for
a broken `main` nor allowed to quietly "fix" pre-existing failures.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.repositories import EventRepository, SessionRepository, TestRunRepository
from devmind.schemas.repo import RepoProfile
from devmind.schemas.session import SessionCreate
from devmind.services.pytest_output_parser import PytestOutputParser
from devmind.services.test_execution_service import TestExecutionService
from tests.fakes.fake_sandbox import FakeSandbox, command_result

_PROFILE = RepoProfile(
    language="python", test_command=("python", "-m", "pytest"), has_test_suite=True
)


def _pytest_output(*failed_node_ids: str, passed: int = 3) -> str:
    lines = ["F" * len(failed_node_ids) + "." * passed + "  [100%]"]
    lines.append("=========================== short test summary info ============================")
    for node_id in failed_node_ids:
        lines.append(f"FAILED {node_id} - assert 0 == 1")
    lines.append(f"{len(failed_node_ids)} failed, {passed} passed in 0.30s")
    return "\n".join(lines) + "\n"


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def _service(db_session: SQLAlchemySession, sandbox: FakeSandbox) -> TestExecutionService:
    return TestExecutionService(
        sandbox,
        PytestOutputParser(),
        TestRunRepository(db_session),
        EventRepository(db_session),
    )


async def test_pre_existing_failure_is_excluded_from_the_verdict(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    already_red = "tests/test_legacy.py::test_flaky"
    sandbox = FakeSandbox(
        [
            command_result(exit_code=1, stdout=_pytest_output(already_red)),  # baseline
            command_result(
                exit_code=1, stdout=_pytest_output(already_red)
            ),  # attempt still red there
        ]
    )
    svc = _service(db_session, sandbox)

    await svc.run_baseline(session_id, _PROFILE)
    result = await svc.run(session_id, _PROFILE, attempt=1)

    assert result.pre_existing_failures == (already_red,)
    assert result.report.failed == 0
    assert result.verified_green is True  # the only failure was pre-existing


async def test_a_new_failure_is_not_excluded(
    db_session: SQLAlchemySession, session_id: str
) -> None:
    already_red = "tests/test_legacy.py::test_flaky"
    regression = "tests/test_calc.py::test_add"
    sandbox = FakeSandbox(
        [
            command_result(exit_code=1, stdout=_pytest_output(already_red)),
            command_result(exit_code=1, stdout=_pytest_output(already_red, regression)),
        ]
    )
    svc = _service(db_session, sandbox)

    await svc.run_baseline(session_id, _PROFILE)
    result = await svc.run(session_id, _PROFILE, attempt=1)

    assert result.pre_existing_failures == (already_red,)
    assert result.verified_green is False
    assert {f.node_id for f in result.report.failures} == {regression}
