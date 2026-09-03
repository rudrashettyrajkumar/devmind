"""SI-4: approval is single-use and session-bound.

The `ApprovalModel` carries an opaque token, a session FK, and a `consumed_at`
timestamp. Once consumed, a replay through the guard raises
`ApprovalAlreadyConsumedError`. A regression here is a broken invariant — fix the
code, never the test.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import ApprovalDecision
from devmind.exceptions import ApprovalAlreadyConsumedError
from tests.safety._approval_kit import GateHarness


async def _approve(harness: GateHarness) -> None:
    await harness.service.request(harness.session_id)
    await harness.service.decide(harness.session_id, ApprovalDecision.APPROVED, decided_by="alice")


async def test_si4_token_is_consumed_exactly_once(db_session: SQLAlchemySession) -> None:
    harness = GateHarness(db_session)
    await _approve(harness)

    first = await harness.guard.authorize(harness.session_id, "open_draft_pr")
    assert first.is_actionable
    await harness.service.consume(harness.session_id)

    with pytest.raises(ApprovalAlreadyConsumedError):
        await harness.guard.authorize(harness.session_id, "open_draft_pr")


async def test_si4_second_consume_raises(db_session: SQLAlchemySession) -> None:
    harness = GateHarness(db_session)
    await _approve(harness)
    await harness.service.consume(harness.session_id)

    with pytest.raises(ApprovalAlreadyConsumedError):
        await harness.service.consume(harness.session_id)


async def test_si4_token_is_opaque_and_bound_to_its_session(
    db_session: SQLAlchemySession,
) -> None:
    harness = GateHarness(db_session)
    record = await harness.service.request(harness.session_id)

    assert record.session_id == harness.session_id
    assert len(record.token) >= 32
    assert harness.session_id not in record.token
