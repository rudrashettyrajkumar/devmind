"""`TestExecutionService` — run the suite, read the result, keep the record (E8-F1).

The agent's belief that it fixed the bug is worthless; the suite is the oracle. This
service assembles the pytest command from `RepoProfile`, runs it in the sandbox,
parses the output through `PytestOutputParser`, persists a `TestRunModel`, and emits
a `TEST_RUN` event.

**Baseline discipline.** `run_baseline()` runs the full suite on the clean checkout
before any edit. Whatever is already red there is recorded and then *subtracted* from
every later verdict — the agent is neither blamed for a broken `main` nor allowed to
quietly "fix" pre-existing failures and balloon the diff.

**No test suite.** `profile.has_test_suite is False` → nothing runs, no row is
written, a `TEST_RUN` event marks the skip, and the returned result has
`skipped is True` (never `verified_green`). The session proceeds as UNVERIFIED; E9
surfaces that in the approval payload.
"""

from __future__ import annotations

import logging

from devmind.core.constants import (
    PYTEST_EXECUTION_ARGS,
    PYTEST_MODULE_INVOCATION,
    PYTEST_TIMEOUT_SECONDS,
)
from devmind.core.enums import EventType
from devmind.interfaces.sandbox import Sandbox
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.test_execution import TestFailureReport, TestRunResult
from devmind.services.pytest_output_parser import PytestOutputParser

logger = logging.getLogger(__name__)


class TestExecutionService:
    """Runs pytest for a session and records every run immutably."""

    def __init__(
        self,
        sandbox: Sandbox,
        parser: PytestOutputParser,
        runs: TestRunRepository,
        events: EventRepository,
        *,
        pytest_timeout_supported: bool = False,
    ) -> None:
        # `pytest_timeout_supported` is a construction-time flag, not a runtime probe:
        # the `--timeout` arg is a diagnostic nicety (the sandbox's own process-group
        # kill is the real hang guard), not worth an extra sandbox round-trip every
        # session to detect. Deployments that build `pytest-timeout` into the image
        # set it true.
        self._sandbox = sandbox
        self._parser = parser
        self._runs = runs
        self._events = events
        self._pytest_timeout_supported = pytest_timeout_supported

    async def run_baseline(self, session_id: str, profile: RepoProfile) -> TestRunResult:
        """Full suite, clean checkout, before any edit. `attempt` is 0."""
        return await self._execute(session_id, profile, attempt=0, is_baseline=True)

    async def run(
        self,
        session_id: str,
        profile: RepoProfile,
        *,
        attempt: int,
        node_ids: list[str] | None = None,
        keyword: str | None = None,
    ) -> TestRunResult:
        """One post-edit run. `node_ids` / `keyword` narrow it for fast iteration;
        the orchestrator always follows a narrowed green with a full run before the
        approval gate.
        """
        return await self._execute(
            session_id,
            profile,
            attempt=attempt,
            is_baseline=False,
            node_ids=node_ids,
            keyword=keyword,
        )

    # --- internals -------------------------------------------------------------

    async def _execute(
        self,
        session_id: str,
        profile: RepoProfile,
        *,
        attempt: int,
        is_baseline: bool,
        node_ids: list[str] | None = None,
        keyword: str | None = None,
    ) -> TestRunResult:
        if not profile.has_test_suite:
            self._events.append(
                session_id,
                EventType.TEST_RUN,
                {
                    "attempt": attempt,
                    "is_baseline": is_baseline,
                    "skipped": True,
                    "reason": "no_test_suite",
                },
            )
            return TestRunResult(
                session_id=session_id, attempt=attempt, is_baseline=is_baseline, skipped=True
            )

        command = SandboxCommand(argv=self._build_argv(profile, node_ids, keyword))
        result = await self._sandbox.run(command)
        raw = self._parser.parse(result)

        pre_existing = () if is_baseline else self._baseline_failures(session_id)
        effective = raw if is_baseline else self._subtract(raw, frozenset(pre_existing))
        subtracted = tuple(
            sorted(f.node_id for f in raw.failures if f.node_id in set(pre_existing))
        )

        run_result = TestRunResult(
            session_id=session_id,
            attempt=attempt,
            is_baseline=is_baseline,
            skipped=False,
            report=effective,
            raw_report=raw,
            pre_existing_failures=subtracted,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
        )
        row = self._runs.create(
            session_id,
            attempt=attempt,
            is_baseline=is_baseline,
            exit_code=result.exit_code,
            passed=effective.passed,
            failed=effective.failed,
            errors=effective.errors,
            signature=effective.signature or None,
            report=run_result.model_dump(mode="json"),
            duration_seconds=result.duration_seconds,
        )
        run_result = run_result.model_copy(update={"test_run_id": row.id})

        self._events.append(
            session_id,
            EventType.TEST_RUN,
            {
                "attempt": attempt,
                "is_baseline": is_baseline,
                "passed": effective.passed,
                "failed": effective.failed,
                "errors": effective.errors,
                "signature": effective.signature,
                "duration_seconds": result.duration_seconds,
                "timed_out": raw.timed_out,
                "unparseable": raw.unparseable,
                "collection_error": raw.collection_error is not None,
                "pre_existing_excluded": len(subtracted),
            },
        )
        return run_result

    def _build_argv(
        self, profile: RepoProfile, node_ids: list[str] | None, keyword: str | None
    ) -> tuple[str, ...]:
        base = profile.test_command or PYTEST_MODULE_INVOCATION
        argv: list[str] = [*base, *PYTEST_EXECUTION_ARGS]
        if self._pytest_timeout_supported:
            argv.append(f"--timeout={PYTEST_TIMEOUT_SECONDS}")
        if keyword:
            argv += ["-k", keyword]
        if node_ids:
            argv += list(node_ids)
        return tuple(argv)

    def _baseline_failures(self, session_id: str) -> tuple[str, ...]:
        row = self._runs.baseline_for_session(session_id)
        if row is None:
            return ()
        baseline = TestRunResult.model_validate(row.report)
        source = baseline.raw_report or baseline.report
        if source is None:
            return ()
        return tuple(f.node_id for f in source.failures)

    @staticmethod
    def _subtract(raw: TestFailureReport, pre_existing: frozenset[str]) -> TestFailureReport:
        """The verdict report: pre-existing failures removed, counts and signature
        recomputed. The failed/error split is not preserved — the pass/fail gate does
        not care which it is — but `raw_report` keeps it for the approval payload.
        """
        if not pre_existing or raw.collection_error is not None:
            return raw
        kept = tuple(f for f in raw.failures if f.node_id not in pre_existing)
        return raw.model_copy(
            update={
                "failures": kept,
                "failed": len(kept),
                "errors": 0 if raw.collection_error is None else raw.errors,
                "signature": TestFailureReport.signature_for(kept),
            }
        )
