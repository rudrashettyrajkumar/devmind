"""Schema-level checks for the approval DTOs (E9-F1)."""

from __future__ import annotations

from datetime import UTC, datetime

from devmind.core.enums import ApprovalDecision
from devmind.schemas.approval import (
    ApprovalRecord,
    TestEvidence,
    TestRunSummary,
)


def _record(**overrides: object) -> ApprovalRecord:
    base: dict[str, object] = {
        "id": "a1",
        "session_id": "s1",
        "token": "tok",
        "decision": None,
        "reason": None,
        "decided_by": None,
        "decided_at": None,
        "consumed_at": None,
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return ApprovalRecord.model_validate(base)


def test_pending_record_is_not_actionable() -> None:
    record = _record()
    assert record.is_pending
    assert not record.is_approved
    assert not record.is_actionable


def test_approved_unconsumed_record_is_actionable() -> None:
    record = _record(decision=ApprovalDecision.APPROVED)
    assert record.is_approved
    assert record.is_actionable


def test_approved_consumed_record_is_not_actionable() -> None:
    record = _record(decision=ApprovalDecision.APPROVED, consumed_at=datetime.now(UTC))
    assert record.is_approved
    assert record.is_consumed
    assert not record.is_actionable


def test_rejected_record_is_not_approved() -> None:
    record = _record(decision=ApprovalDecision.REJECTED, reason="no")
    assert not record.is_approved
    assert not record.is_actionable


def test_test_evidence_render_flags_unverified() -> None:
    evidence = TestEvidence(unverified=True)
    assert "UNVERIFIED" in evidence.render()


def test_test_evidence_render_shows_baseline_and_final() -> None:
    baseline = TestRunSummary(
        attempt=0,
        is_baseline=True,
        exit_code=1,
        passed=10,
        failed=1,
        errors=0,
        signature=None,
        duration_seconds=1.0,
    )
    final = TestRunSummary(
        attempt=2,
        is_baseline=False,
        exit_code=0,
        passed=11,
        failed=0,
        errors=0,
        signature="sig",
        duration_seconds=0.8,
    )
    text = TestEvidence(
        baseline=baseline,
        final=final,
        attempts=(final,),
        pre_existing_failures=("tests/test_x.py::test_old",),
    ).render()
    assert "baseline: 10 passed, 1 failed" in text
    assert "final: 11 passed, 0 failed" in text
    assert "tests/test_x.py::test_old" in text
