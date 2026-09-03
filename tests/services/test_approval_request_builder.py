"""`ApprovalRequestBuilder` — every payload field populated, warnings when true (E9-F1-T3).

The warnings list is load-bearing: this asserts each `WARNING_*` string appears
exactly when its condition holds and not otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import (
    WARNING_COST_CEILING,
    WARNING_SUBPROCESS_SANDBOX,
    WARNING_TESTS_ONLY_DIFF,
    WARNING_UNVERIFIED_NO_TESTS,
)
from devmind.core.enums import SandboxBackend, SessionStatus
from devmind.prompts.loader import PromptLoader
from devmind.repositories import (
    EventRepository,
    SessionRepository,
    TestRunRepository,
    TodoRepository,
)
from devmind.schemas.session import SessionCreate
from devmind.schemas.test_execution import TestFailure, TestFailureReport, TestRunResult
from devmind.services.approval_request_builder import ApprovalRequestBuilder
from devmind.services.change_summary_service import ChangeSummaryService
from devmind.services.diff_service import DiffService
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.workspace_path_guard import WorkspacePathGuard
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text
from tests.fakes.fake_sandbox import FakeSandbox, command_result

_SUMMARY_MD = """\
### Issue understanding

The reporter needs parse_timestamp to accept naive datetimes.

### Summary

It raised on naive input; it now assumes UTC.

### Changes by file

- src/pkg/parser.py — coerce naive datetimes to UTC.

### Verification

final: 12 passed, 0 failed.

### Risks and uncertainties

- The UTC assumption may be wrong for local-time callers.
"""

_TO_SUMMARIZING = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)

_DIFF = "diff --git a/src/pkg/parser.py b/src/pkg/parser.py\n+utc coerce\n"
_NUMSTAT_SRC = "5\t2\tsrc/pkg/parser.py\n"
_NUMSTAT_TESTS = "5\t0\ttests/test_parser.py\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _seed_session(
    db_session: SQLAlchemySession, workspace: Path, *, has_test_suite: bool = True
) -> str:
    repo = SessionRepository(db_session)
    machine = SessionStateMachine(repo, EventRepository(db_session))
    model = repo.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=42))
    repo.record_ingestion(
        model.id,
        base_commit_sha="abc123",
        default_branch="main",
        workspace_path=str(workspace),
        has_test_suite=has_test_suite,
        issue_title="parse_timestamp rejects naive datetimes",
        issue_body="It should assume UTC.",
    )
    for step in _TO_SUMMARIZING:
        machine.transition(model.id, step)
    TodoRepository(db_session).replace_all(model.id, ["Coerce naive datetimes to UTC"])
    return model.id


def _builder(
    db_session: SQLAlchemySession,
    workspace: Path,
    *,
    numstat: str = _NUMSTAT_SRC,
    max_cost: float = 5.0,
) -> ApprovalRequestBuilder:
    # sandbox.run order: summarize→git diff, builder→git diff, file_stats→numstat,
    # touches_only_tests→numstat.
    sandbox = FakeSandbox(
        [
            command_result(stdout=_DIFF),
            command_result(stdout=_DIFF),
            command_result(stdout=numstat),
            command_result(stdout=numstat),
        ]
    )
    diffs = DiffService(sandbox, WorkspacePathGuard(workspace))
    summaries = ChangeSummaryService(
        FakeLLMProvider([final_text(_SUMMARY_MD)]), PromptLoader(), diffs
    )
    return ApprovalRequestBuilder(
        SessionRepository(db_session),
        TodoRepository(db_session),
        TestRunRepository(db_session),
        summaries,
        diffs,
        max_session_cost_usd=max_cost,
    )


async def test_every_field_is_populated(db_session: SQLAlchemySession, workspace: Path) -> None:
    session_id = _seed_session(db_session, workspace)
    runs = TestRunRepository(db_session)
    runs.create(
        session_id,
        attempt=0,
        is_baseline=True,
        exit_code=0,
        passed=12,
        failed=0,
        errors=0,
        signature=None,
        report={},
        duration_seconds=1.0,
    )
    runs.create(
        session_id,
        attempt=1,
        is_baseline=False,
        exit_code=0,
        passed=12,
        failed=0,
        errors=0,
        signature="sig",
        report={},
        duration_seconds=0.9,
    )

    payload = await _builder(db_session, workspace).build(session_id)

    assert payload.session_id == session_id
    assert payload.repo_url == "https://github.com/x/y"
    assert payload.issue is not None and payload.issue.number == 42
    assert "parse_timestamp" in payload.issue_understanding
    assert [item.content for item in payload.plan] == ["Coerce naive datetimes to UTC"]
    assert payload.summary.risk_notes
    assert payload.risk_notes == payload.summary.risk_notes
    assert "+utc coerce" in payload.diff
    assert [(s.path, s.added, s.removed) for s in payload.diff_stats] == [
        ("src/pkg/parser.py", 5, 2)
    ]
    assert payload.test_evidence.baseline is not None
    assert payload.test_evidence.final is not None
    assert payload.test_evidence.unverified is False
    assert payload.metrics.total_steps == 0
    assert payload.warnings == ()


async def test_unverified_warning_when_no_test_suite(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    session_id = _seed_session(db_session, workspace, has_test_suite=False)
    payload = await _builder(db_session, workspace).build(session_id)
    assert WARNING_UNVERIFIED_NO_TESTS in payload.warnings
    assert payload.test_evidence.unverified is True


async def test_tests_only_warning_when_diff_touches_only_tests(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    session_id = _seed_session(db_session, workspace)
    payload = await _builder(db_session, workspace, numstat=_NUMSTAT_TESTS).build(session_id)
    assert WARNING_TESTS_ONLY_DIFF in payload.warnings


async def test_cost_ceiling_warning(db_session: SQLAlchemySession, workspace: Path) -> None:
    session_id = _seed_session(db_session, workspace)
    SessionRepository(db_session).record_usage(
        session_id, input_tokens=0, output_tokens=0, cache_read_tokens=0, cost_usd=9.99
    )
    payload = await _builder(db_session, workspace, max_cost=5.0).build(session_id)
    assert WARNING_COST_CEILING in payload.warnings


async def test_subprocess_sandbox_warning(db_session: SQLAlchemySession, workspace: Path) -> None:
    session_id = _seed_session(db_session, workspace)
    row = SessionRepository(db_session).get_by_id(session_id)
    assert row is not None
    row.sandbox_backend = SandboxBackend.SUBPROCESS
    db_session.commit()

    payload = await _builder(db_session, workspace).build(session_id)
    assert WARNING_SUBPROCESS_SANDBOX in payload.warnings


async def test_pre_existing_failures_surface_from_the_baseline(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    session_id = _seed_session(db_session, workspace)
    baseline = TestRunResult(
        session_id=session_id,
        attempt=0,
        is_baseline=True,
        raw_report=TestFailureReport(
            total=3,
            passed=2,
            failed=1,
            failures=(TestFailure(node_id="tests/test_x.py::test_old"),),
        ),
        report=TestFailureReport(total=3, passed=2, failed=1),
    )
    TestRunRepository(db_session).create(
        session_id,
        attempt=0,
        is_baseline=True,
        exit_code=1,
        passed=2,
        failed=1,
        errors=0,
        signature=None,
        report=baseline.model_dump(mode="json"),
        duration_seconds=1.0,
    )

    payload = await _builder(db_session, workspace).build(session_id)
    assert payload.test_evidence.pre_existing_failures == ("tests/test_x.py::test_old",)
