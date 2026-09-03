"""`ApprovalRequestBuilder` — assembles the whole review payload (E9-F1-T3).

One method, `build(session_id)`, gathers everything design §9 says a human needs to
decide in ninety seconds: the issue as understood, the plan as worked, the change
summary and risk notes, the full (capped) diff and per-file stats, the test evidence,
the run's cost in every currency, and — the load-bearing part — the `warnings` list.

Each `WARNING_*` string from `core/constants.py` is added here, verbatim, exactly
when its condition holds:

* no test suite in the repo                    → UNVERIFIED
* the diff touches only test files             → tests-only
* the run reached its configured cost ceiling  → cost ceiling
* the sandbox was the `subprocess` backend     → not a security boundary
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from devmind.core.constants import (
    LANGUAGE_UNKNOWN,
    WARNING_COST_CEILING,
    WARNING_SUBPROCESS_SANDBOX,
    WARNING_TESTS_ONLY_DIFF,
    WARNING_UNVERIFIED_NO_TESTS,
)
from devmind.core.enums import IssueState, SandboxBackend
from devmind.exceptions import SessionNotFoundError, WorkspaceError
from devmind.models.base import utcnow
from devmind.models.test_run import TestRunModel
from devmind.repositories.session_repository import SessionRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.approval import (
    ApprovalRequest,
    SessionMetrics,
    TestEvidence,
    TestRunSummary,
)
from devmind.schemas.github import IssueRead
from devmind.schemas.repo import RepoProfile
from devmind.schemas.session import SessionRead
from devmind.schemas.test_execution import TestRunResult
from devmind.schemas.todo import TodoItemRead
from devmind.services.change_summary_service import ChangeSummaryService
from devmind.services.diff_service import DiffService


class ApprovalRequestBuilder:
    """Builds the `ApprovalRequest` payload for one session."""

    def __init__(
        self,
        sessions: SessionRepository,
        todos: TodoRepository,
        runs: TestRunRepository,
        summaries: ChangeSummaryService,
        diffs: DiffService,
        *,
        max_session_cost_usd: float,
    ) -> None:
        self._sessions = sessions
        self._todos = todos
        self._runs = runs
        self._summaries = summaries
        self._diffs = diffs
        self._max_session_cost_usd = max_session_cost_usd

    async def build(self, session_id: str) -> ApprovalRequest:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        if model.workspace_path is None:
            raise WorkspaceError(
                f"session {session_id} has no workspace — cannot build a review payload",
                details={"session_id": session_id},
            )

        session = SessionRead.model_validate(model)
        workspace = Path(model.workspace_path)

        plan = tuple(
            TodoItemRead.model_validate(row) for row in self._todos.list_for_session(session_id)
        )
        evidence = self._test_evidence(session_id, has_test_suite=model.has_test_suite)

        summary = await self._summaries.summarize(
            session,
            plan_text=_format_plan(plan),
            test_evidence_text=evidence.render(),
        )

        diff = await self._diffs.unified_diff(workspace)
        diff_stats = tuple(await self._diffs.file_stats(workspace))
        tests_only = await self._diffs.touches_only_tests(
            workspace,
            RepoProfile(language=LANGUAGE_UNKNOWN, has_test_suite=model.has_test_suite),
        )

        return ApprovalRequest(
            session_id=session_id,
            repo_url=session.repo_url,
            issue=self._issue(session.issue_number, session.issue_title, session.issue_body),
            issue_understanding=summary.issue_understanding,
            plan=plan,
            summary=summary,
            diff=diff,
            diff_stats=diff_stats,
            test_evidence=evidence,
            risk_notes=summary.risk_notes,
            warnings=self._warnings(session, diff=diff, tests_only=tests_only),
            metrics=self._metrics(session),
            created_at=utcnow(),
        )

    # --- test evidence -------------------------------------------------------

    def _test_evidence(self, session_id: str, *, has_test_suite: bool) -> TestEvidence:
        baseline_row = self._runs.baseline_for_session(session_id)
        attempt_rows = self._runs.attempts_for_session(session_id)
        attempts = tuple(_summarise_run(row) for row in attempt_rows)
        return TestEvidence(
            baseline=_summarise_run(baseline_row) if baseline_row is not None else None,
            final=attempts[-1] if attempts else None,
            attempts=attempts,
            pre_existing_failures=_pre_existing_failures(baseline_row),
            unverified=not has_test_suite,
        )

    # --- warnings ----------------------------------------------------------

    def _warnings(self, session: SessionRead, *, diff: str, tests_only: bool) -> tuple[str, ...]:
        warnings: list[str] = []
        if not session.has_test_suite:
            warnings.append(WARNING_UNVERIFIED_NO_TESTS)
        if diff.strip() and tests_only:
            warnings.append(WARNING_TESTS_ONLY_DIFF)
        if session.estimated_cost_usd >= self._max_session_cost_usd:
            warnings.append(WARNING_COST_CEILING)
        if session.sandbox_backend is SandboxBackend.SUBPROCESS:
            warnings.append(WARNING_SUBPROCESS_SANDBOX)
        return tuple(warnings)

    # --- metrics ---------------------------------------------------------

    @staticmethod
    def _metrics(session: SessionRead) -> SessionMetrics:
        end = session.completed_at or utcnow()
        wall = _seconds_between(session.created_at, end)
        return SessionMetrics(
            fix_attempts=session.fix_attempts,
            total_steps=session.total_steps,
            wall_time_seconds=wall,
            input_tokens=session.input_tokens,
            output_tokens=session.output_tokens,
            cache_read_tokens=session.cache_read_tokens,
            cost_usd=session.estimated_cost_usd,
        )

    @staticmethod
    def _issue(number: int | None, title: str | None, body: str | None) -> IssueRead | None:
        if number is None:
            return None
        return IssueRead(
            number=number,
            title=title or f"issue #{number}",
            body=body or "",
            state=IssueState.OPEN,
        )


def _seconds_between(start: datetime, end: datetime) -> float:
    """Wall-clock seconds, tolerant of the naive datetimes SQLite hands back (the
    timestamp columns are stored without tzinfo, so `start` may be naive while
    `end` — a fresh `utcnow()` — is aware).
    """
    naive_start = start.astimezone(UTC).replace(tzinfo=None) if start.tzinfo else start
    naive_end = end.astimezone(UTC).replace(tzinfo=None) if end.tzinfo else end
    return max(0.0, (naive_end - naive_start).total_seconds())


def _format_plan(plan: tuple[TodoItemRead, ...]) -> str:
    if not plan:
        return "(no plan recorded)"
    return "\n".join(
        f"{index}. [{item.status.value}] {item.content}" for index, item in enumerate(plan, start=1)
    )


def _summarise_run(row: TestRunModel) -> TestRunSummary:
    return TestRunSummary(
        attempt=row.attempt,
        is_baseline=row.is_baseline,
        exit_code=row.exit_code,
        passed=row.passed,
        failed=row.failed,
        errors=row.errors,
        signature=row.signature,
        duration_seconds=row.duration_seconds,
    )


def _pre_existing_failures(baseline_row: TestRunModel | None) -> tuple[str, ...]:
    if baseline_row is None:
        return ()
    try:
        result = TestRunResult.model_validate(baseline_row.report)
    except ValidationError:
        return ()
    source = result.raw_report or result.report
    if source is None:
        return ()
    return tuple(sorted(failure.node_id for failure in source.failures))
