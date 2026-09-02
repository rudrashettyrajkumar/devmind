"""DTOs for test execution and self-correction (E8).

`PytestOutputParser` turns a raw `CommandResult` into a `TestFailureReport`; the
`signature` on that report is what makes no-progress detection possible — identical
signatures on consecutive attempts mean the last edit changed nothing that mattered.

`TestExecutionService` wraps a report in a `TestRunResult`, which additionally knows
which failures were already red on the clean checkout (the baseline) and therefore
do not count against the agent's verdict.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.constants import (
    TEST_FAILURE_TRACEBACK_MAX_LINES,
)
from devmind.core.enums import CorrectionAction


class TestFailure(BaseModel):
    """One failing or erroring test. `traceback` is trimmed to the frames that sit
    inside the repository — the site-packages frames above them carry no signal for
    a fix and cost tokens in the retry prompt.
    """

    model_config = ConfigDict(frozen=True)

    node_id: str
    file: str | None = None
    line: int | None = None
    exception_type: str | None = None
    message: str = ""
    traceback: str = ""


class TestFailureReport(BaseModel):
    """The structured outcome of one pytest run — never a wall of text.

    `succeeded` is the raw reading of *this* run in isolation. Whether a run is a
    *verdict* pass is `TestRunResult.verified_green`, which also subtracts the
    pre-existing (baseline) failures this property knows nothing about.
    """

    model_config = ConfigDict(frozen=True)

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failures: tuple[TestFailure, ...] = ()
    collection_error: str | None = None
    timed_out: bool = False
    unparseable: bool = False
    signature: str = ""
    truncated_output: str = ""

    @property
    def succeeded(self) -> bool:
        """True only for an unambiguously green run. A killed or unparseable run is
        never green — the guard the whole epic turns on.
        """
        return (
            self.failed == 0
            and self.errors == 0
            and not self.timed_out
            and not self.unparseable
            and self.collection_error is None
        )

    @staticmethod
    def signature_for(failures: Iterable[TestFailure]) -> str:
        """A stable hash of the failure set: sorted `node_id:exception_type` pairs.

        Insensitive to ordering and to line-number drift, sensitive to a genuinely
        different failure. An empty failure set hashes to a fixed value, which is
        fine — a report with no failures is never compared for no-progress.
        """
        joined = "|".join(sorted(f"{f.node_id}:{f.exception_type}" for f in failures))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    @staticmethod
    def mode_signature(token: str) -> str:
        """A signature for a failure *mode* with no per-test node ids — a timeout, an
        unparseable run, a collection error. Keeps `SelfCorrectionController`'s
        `signature == previous_signature` no-progress rule working for "the run blew
        up the same way twice".
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def render(self) -> str:
        """A compact human-readable block for `test_failure_analysis.md`. Pure."""
        if self.timed_out:
            return "The test run timed out and was killed before producing any result."
        if self.unparseable:
            return (
                "The test run exited abnormally with no parseable pytest summary. "
                f"Raw tail:\n{self.truncated_output}"
            )
        if self.collection_error is not None:
            return f"Test collection failed before any test ran:\n{self.collection_error}"

        header = (
            f"{self.failed} failed, {self.errors} error(s), {self.passed} passed (of {self.total})."
        )
        blocks: list[str] = [header]
        for failure in self.failures:
            location = failure.file or "?"
            if failure.line is not None:
                location = f"{location}:{failure.line}"
            exc = f" [{failure.exception_type}]" if failure.exception_type else ""
            body = failure.traceback or failure.message
            trimmed = "\n".join(body.splitlines()[:TEST_FAILURE_TRACEBACK_MAX_LINES])
            blocks.append(f"### {failure.node_id}{exc}\n{location}\n{trimmed}".rstrip())
        return "\n\n".join(blocks)


class TestRunResult(BaseModel):
    """Everything one `TestExecutionService.run()` / `run_baseline()` call produced.

    `report` has the baseline's pre-existing failures removed; `raw_report` is
    exactly what pytest emitted. `skipped` is the "repo has no test suite" case —
    the session proceeds, but `verified_green` is `False`: unverified is not passing.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    attempt: int
    is_baseline: bool = False
    skipped: bool = False
    report: TestFailureReport | None = None
    raw_report: TestFailureReport | None = None
    pre_existing_failures: tuple[str, ...] = ()
    exit_code: int = 0
    duration_seconds: float = 0.0
    test_run_id: str | None = None

    @property
    def verified_green(self) -> bool:
        """The verdict: a real run whose only-the-agent's-fault failures are all gone."""
        return not self.skipped and self.report is not None and self.report.succeeded


class CorrectionDecision(BaseModel):
    """`SelfCorrectionController.decide()`'s output — the branch the orchestrator takes."""

    model_config = ConfigDict(frozen=True)

    action: CorrectionAction
    reason: str
    attempts_remaining: int = Field(ge=0)
