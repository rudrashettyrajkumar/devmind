"""DTOs for the human approval gate and its review payload (E9).

Three groups live here:

* `ApprovalRecord` — the gate's own state, projected from `ApprovalModel`. The
  return type of every `ApprovalService` method and of `RemoteOperationGuard.authorize()`.
* the review-payload parts — `FileDiffStat`, `TestRunSummary`, `TestEvidence`,
  `SessionMetrics`, `ChangeSummary` — each a small, self-describing piece of what a
  human needs to decide.
* `ApprovalRequest` — the whole payload, assembled by `ApprovalRequestBuilder`.

`ApprovalRequest.warnings` is the load-bearing field (spec §"The review payload"):
the strings in `core/constants.py` (`WARNING_*`) appear here, verbatim, exactly when
their condition holds.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from devmind.core.enums import ApprovalDecision
from devmind.schemas.github import IssueRead
from devmind.schemas.todo import TodoItemRead


class ApprovalRecord(BaseModel):
    """One session's approval row, as every `ApprovalService` method returns it.

    `decision is None` is an open request awaiting a human; a set `decision` is
    final. `consumed_at` is written exactly once, by `PRService` after the PR opens —
    a second consume is `ApprovalAlreadyConsumedError` (SI-4).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    session_id: str
    token: str
    decision: ApprovalDecision | None
    reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    consumed_at: datetime | None
    created_at: datetime

    @property
    def is_pending(self) -> bool:
        """No human has decided yet."""
        return self.decision is None

    @property
    def is_approved(self) -> bool:
        return self.decision is ApprovalDecision.APPROVED

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @property
    def is_actionable(self) -> bool:
        """`APPROVED` and not yet spent — the only state a remote op may proceed on."""
        return self.is_approved and not self.is_consumed


class FileDiffStat(BaseModel):
    """Per-file line churn for one path in the diff. A binary file reports 0/0."""

    model_config = ConfigDict(frozen=True)

    path: str
    added: int
    removed: int


class TestRunSummary(BaseModel):
    """One persisted `TestRunModel`, flattened for the payload — no tracebacks, just
    the counts a reviewer scans.
    """

    model_config = ConfigDict(frozen=True)

    attempt: int
    is_baseline: bool
    exit_code: int
    passed: int
    failed: int
    errors: int
    signature: str | None
    duration_seconds: float


class TestEvidence(BaseModel):
    """The test story: where the suite started, where it ended, and every attempt in
    between. `unverified` is `True` when no real suite ran — the session proceeded
    but nothing was proven (spec §TestEvidence).
    """

    model_config = ConfigDict(frozen=True)

    baseline: TestRunSummary | None = None
    final: TestRunSummary | None = None
    attempts: tuple[TestRunSummary, ...] = ()
    pre_existing_failures: tuple[str, ...] = ()
    unverified: bool = False

    def render(self) -> str:
        """A compact plain-text block for the `change_summary` prompt. Pure."""
        if self.unverified:
            return "No test suite ran for this session — the change is UNVERIFIED."

        def line(label: str, run: TestRunSummary | None) -> str:
            if run is None:
                return f"{label}: (none)"
            return (
                f"{label}: {run.passed} passed, {run.failed} failed, "
                f"{run.errors} error(s) (exit {run.exit_code})"
            )

        lines = [line("baseline", self.baseline), line("final", self.final)]
        if len(self.attempts) > 1:
            lines.append(f"fix attempts recorded: {len(self.attempts)}")
        if self.pre_existing_failures:
            lines.append(
                "pre-existing failures excluded from the verdict: "
                + ", ".join(self.pre_existing_failures)
            )
        return "\n".join(lines)


class SessionMetrics(BaseModel):
    """What the run cost, in every currency a reviewer weighs: attempts, steps, wall
    time, tokens, and dollars (design §9).
    """

    model_config = ConfigDict(frozen=True)

    fix_attempts: int
    total_steps: int
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float


class ChangeSummary(BaseModel):
    """`ChangeSummaryService`'s output: the reviewer-facing narrative plus the two
    sections pulled out for the payload's own fields.

    `issue_understanding` and `risk_notes` are **required** to be non-empty — an
    agent that reports only confidence has not been useful (spec §ChangeSummaryService).
    """

    model_config = ConfigDict(frozen=True)

    markdown: str
    issue_understanding: str
    risk_notes: tuple[str, ...]


class ApprovalRequest(BaseModel):
    """The whole handoff payload — what `GET /sessions/{id}/approval-request` returns
    (E11) and what a human reviews before anything leaves the machine.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    repo_url: str
    issue: IssueRead | None
    issue_understanding: str
    plan: tuple[TodoItemRead, ...]
    summary: ChangeSummary
    diff: str
    diff_stats: tuple[FileDiffStat, ...]
    test_evidence: TestEvidence
    risk_notes: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: SessionMetrics
    created_at: datetime
