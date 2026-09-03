"""SI-3: no remote-capable operation proceeds without a persisted APPROVED record.

`RemoteOperationGuard.authorize()` is safety layer 3 — it re-reads the approval from
the database at the point of use and refuses anything that is not `APPROVED` and
unconsumed. Layer 2 (the state machine: `PR_OPENED` reachable only from `APPROVED`)
is asserted structurally here too.

E10's `PRService` adds the "unapproved session performs zero git operations" test on
top of this guard. A regression here is a broken invariant — fix the code, never the
test.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import _LEGAL_TRANSITIONS as LEGAL_TRANSITIONS
from devmind.core.enums import ApprovalDecision, SessionStatus
from devmind.exceptions import ApprovalRequiredError
from tests.safety._approval_kit import GateHarness


async def test_si3_guard_refuses_a_session_that_was_never_summarized(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    # never called request() → no approval row at all
    with pytest.raises(ApprovalRequiredError):
        await harness.guard.authorize(harness.session_id, "open_draft_pr")


async def test_si3_guard_refuses_while_awaiting_approval(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    await harness.service.request(harness.session_id)
    with pytest.raises(ApprovalRequiredError):
        await harness.guard.authorize(harness.session_id, "open_draft_pr")


async def test_si3_guard_refuses_a_rejected_session(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    await harness.service.request(harness.session_id)
    await harness.service.decide(
        harness.session_id, ApprovalDecision.REJECTED, decided_by="x", reason="no"
    )
    with pytest.raises(ApprovalRequiredError):
        await harness.guard.authorize(harness.session_id, "open_draft_pr")


async def test_si3_guard_allows_an_approved_unconsumed_session(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    await harness.service.request(harness.session_id)
    await harness.service.decide(harness.session_id, ApprovalDecision.APPROVED, decided_by="alice")
    record = await harness.guard.authorize(harness.session_id, "open_draft_pr")
    assert record.is_actionable


def test_si3_pr_opened_is_reachable_only_from_approved() -> None:
    sources = [
        status
        for status in SessionStatus
        if SessionStatus.PR_OPENED in LEGAL_TRANSITIONS.get(status, frozenset())
    ]
    assert sources == [SessionStatus.APPROVED]


def test_si3_approved_is_reachable_only_from_awaiting_approval() -> None:
    sources = [
        status
        for status in SessionStatus
        if SessionStatus.APPROVED in LEGAL_TRANSITIONS.get(status, frozenset())
    ]
    assert sources == [SessionStatus.AWAITING_APPROVAL]
