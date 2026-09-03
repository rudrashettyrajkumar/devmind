"""`PrBodyComposer` — every mandatory section present, the deterministic provenance
footer always appended, and the evidence block format (E10-F2-T2 / spec `test_pr_body.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from devmind.core.enums import SandboxBackend
from devmind.exceptions import LLMProviderError
from devmind.prompts.loader import PromptLoader
from devmind.schemas.approval import (
    ApprovalRecord,
    ApprovalRequest,
    ChangeSummary,
    SessionMetrics,
    TestEvidence,
    TestRunSummary,
)
from devmind.schemas.session import SessionRead
from devmind.services.pr_body_composer import PrBodyComposer
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text

_GOOD_PROSE = """\
## Summary

Coerce naive datetimes to UTC.

## The issue

parse_timestamp raised on naive input.

Closes #42

## Changes

- src/pkg/parser.py — assume UTC.

## Test evidence

```
baseline: 12 passed, 0 failed
```

Green.

## Risks and what to review closely

- Confirm UTC is right here.
"""


def _run(passed: int = 12, failed: int = 0) -> TestRunSummary:
    return TestRunSummary(
        attempt=0,
        is_baseline=False,
        exit_code=0 if failed == 0 else 1,
        passed=passed,
        failed=failed,
        errors=0,
        signature=None,
        duration_seconds=1.0,
    )


def _review(*, cost: float = 0.83, attempts: int = 1) -> ApprovalRequest:
    evidence = TestEvidence(
        baseline=_run(),
        final=_run(),
        attempts=tuple(_run() for _ in range(attempts)),
    )
    return ApprovalRequest(
        session_id="3f9a",
        repo_url="https://github.com/acme/widget",
        issue=None,
        issue_understanding="parse_timestamp must accept naive datetimes.",
        plan=(),
        summary=ChangeSummary(
            markdown="### Summary\n\nUTC coercion.",
            issue_understanding="parse_timestamp must accept naive datetimes.",
            risk_notes=("UTC may be wrong for local-time callers.",),
        ),
        diff="+utc",
        diff_stats=(),
        test_evidence=evidence,
        risk_notes=("UTC may be wrong for local-time callers.",),
        warnings=(),
        metrics=SessionMetrics(
            fix_attempts=attempts,
            total_steps=10,
            wall_time_seconds=5.0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=cost,
        ),
        created_at=datetime.now(UTC),
    )


def _session(issue_number: int | None = 42) -> SessionRead:
    now = datetime.now(UTC)
    return SessionRead(
        id="3f9a",
        repo_url="https://github.com/acme/widget",
        issue_number=issue_number,
        issue_title="parse_timestamp rejects naive datetimes",
        issue_body="assume UTC",
        base_commit_sha="base",
        default_branch="main",
        workspace_path="/tmp/ws",
        branch_name=None,
        status="approved",  # type: ignore[arg-type]
        sandbox_backend=SandboxBackend.DOCKER,
        fix_attempts=1,
        total_steps=10,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        estimated_cost_usd=0.83,
        has_test_suite=True,
        failure_reason=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def _approval() -> ApprovalRecord:
    now = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    return ApprovalRecord(
        id="ap1",
        session_id="3f9a",
        token="tok",
        decision="approved",  # type: ignore[arg-type]
        reason=None,
        decided_by="Dana Reviewer",
        decided_at=now,
        consumed_at=None,
        created_at=now,
    )


async def test_all_mandatory_sections_and_the_provenance_footer_are_present() -> None:
    composer = PrBodyComposer(FakeLLMProvider([final_text(_GOOD_PROSE)]), PromptLoader())

    body = await composer.compose(
        session=_session(),
        review=_review(),
        approval=_approval(),
        model="claude-opus-5",
        max_fix_attempts=3,
    )

    for heading in (
        "## Summary",
        "## The issue",
        "## Changes",
        "## Test evidence",
        "## Risks and what to review closely",
        "## Provenance",
    ):
        assert heading in body

    assert "Produced autonomously by DevMind (session `3f9a`)" in body
    assert "approved by Dana Reviewer on 2026-09-03 14:30 UTC" in body
    assert "Sandbox: docker" in body
    assert "Model: claude-opus-5" in body
    assert "Cost: $0.83" in body
    assert body.rstrip().endswith("This PR is a draft and has not been merged.")


async def test_missing_mandatory_section_is_an_unusable_response() -> None:
    prose = _GOOD_PROSE.replace("## Risks and what to review closely", "## Notes")
    composer = PrBodyComposer(FakeLLMProvider([final_text(prose)]), PromptLoader())

    with pytest.raises(LLMProviderError):
        await composer.compose(
            session=_session(),
            review=_review(),
            approval=_approval(),
            model="claude-opus-5",
            max_fix_attempts=3,
        )


def test_evidence_block_format() -> None:
    block = PrBodyComposer.render_evidence(_review(attempts=2).test_evidence, max_fix_attempts=3)
    assert "baseline:" in block
    assert "final:" in block
    assert "fix attempts used: 2 of 3" in block


def test_evidence_block_when_unverified() -> None:
    block = PrBodyComposer.render_evidence(TestEvidence(unverified=True), max_fix_attempts=3)
    assert "UNVERIFIED" in block


async def test_no_issue_number_drops_the_closes_line_source() -> None:
    # issue_reference becomes the placeholder; the prompt is told to omit `Closes …`.
    composer = PrBodyComposer(FakeLLMProvider([final_text(_GOOD_PROSE)]), PromptLoader())
    body = await composer.compose(
        session=_session(issue_number=None),
        review=_review(),
        approval=_approval(),
        model="claude-opus-5",
        max_fix_attempts=3,
    )
    assert "## Provenance" in body
    # the rendered prompt carried the placeholder, not a bare "#"
    sent = composer._llm.requests[0].messages[0]["content"][0]["text"]  # type: ignore[index]
    assert "no linked issue" in sent
