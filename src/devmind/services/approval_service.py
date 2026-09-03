"""`ApprovalService` — the gate the whole project rests on (E9-F2).

`SUMMARIZING → AWAITING_APPROVAL → APPROVED | REJECTED`, and nothing else. Every
method here is deliberately strict:

* `request()` runs only from `SUMMARIZING` — the state machine refuses any other
  source, so a caller cannot ask for approval on a session that has not finished
  its work.
* `decide()` runs only from `AWAITING_APPROVAL`, exactly once. A second call raises:
  a decision is final.
* `decided_by` is required by the signature — an approval with no named human is not
  an approval, and that name ends up in the commit trailer and the PR body.
* A rejection must carry a reason.
* **There is no timeout and no auto-approve.** `AWAITING_APPROVAL` is durable and
  waits forever. A timeout that defaulted either way would void the safety model or
  invent a behaviour nobody asked for; neither exists anywhere in this codebase.

`assert_approved()` / `consume()` are what `RemoteOperationGuard` and `PRService`
(E10) call — the token is single-use (SI-4).
"""

from __future__ import annotations

import logging
import secrets
from typing import Final

from devmind.core.enums import ApprovalDecision, EventType, SessionStatus
from devmind.exceptions import (
    ApprovalAlreadyConsumedError,
    ApprovalDecisionError,
    ApprovalRequiredError,
    SessionNotFoundError,
)
from devmind.repositories.approval_repository import ApprovalRepository
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.approval import ApprovalRecord
from devmind.services.session_state_machine import SessionStateMachine

logger = logging.getLogger(__name__)

_TOKEN_BYTES: Final[int] = 32


class ApprovalService:
    """Owns every legal move through the human approval gate."""

    def __init__(
        self,
        approvals: ApprovalRepository,
        sessions: SessionRepository,
        state: SessionStateMachine,
        events: EventRepository,
    ) -> None:
        self._approvals = approvals
        self._sessions = sessions
        self._state = state
        self._events = events

    async def request(self, session_id: str) -> ApprovalRecord:
        """`SUMMARIZING → AWAITING_APPROVAL`. Creates the single-use token.

        The state-machine transition is what enforces the source state: called from
        anywhere other than `SUMMARIZING` it raises `InvalidStateTransitionError`
        and nothing is created.
        """
        self._require_session(session_id)
        self._state.transition(session_id, SessionStatus.AWAITING_APPROVAL)

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        model = self._approvals.create(session_id, token=token)
        self._events.append(
            session_id,
            EventType.APPROVAL_REQUESTED,
            {"approval_id": model.id},
        )
        logger.info("session %s is now AWAITING_APPROVAL (approval %s)", session_id, model.id)
        return ApprovalRecord.model_validate(model)

    async def decide(
        self,
        session_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        """`AWAITING_APPROVAL → APPROVED | REJECTED`, once and only once."""
        if not decided_by.strip():
            raise ApprovalDecisionError(
                f"a decision on session {session_id} must name the deciding human",
                details={"session_id": session_id},
            )
        if decision is ApprovalDecision.REJECTED and not (reason and reason.strip()):
            raise ApprovalDecisionError(
                f"rejecting session {session_id} requires a reason",
                details={"session_id": session_id},
            )

        record = self._approvals.get_by_session(session_id)
        if record is None:
            raise ApprovalRequiredError(
                f"session {session_id} has no approval request to decide",
                details={"session_id": session_id},
            )
        if record.decision is not None:
            raise ApprovalDecisionError(
                f"session {session_id} was already decided ({record.decision.value}) — "
                "a decision is final",
                details={"session_id": session_id, "existing_decision": record.decision.value},
            )

        target = (
            SessionStatus.APPROVED
            if decision is ApprovalDecision.APPROVED
            else SessionStatus.REJECTED
        )
        self._state.transition(session_id, target, reason=reason)
        updated = self._approvals.decide(session_id, decision, decided_by=decided_by, reason=reason)
        self._events.append(
            session_id,
            EventType.APPROVAL_DECIDED,
            {
                "decision": decision.value,
                "decided_by": decided_by,
                "reason": reason,
            },
        )
        logger.info("session %s decided %s by %s", session_id, decision.value, decided_by)
        return ApprovalRecord.model_validate(updated)

    async def assert_approved(self, session_id: str) -> ApprovalRecord:
        """Return the record iff it is `APPROVED` and unconsumed; raise otherwise.

        Raises `ApprovalRequiredError` when there is no approval or it is not
        approved, `ApprovalAlreadyConsumedError` when the token has been spent.
        """
        record = self._approvals.get_by_session(session_id)
        if record is None or record.decision is not ApprovalDecision.APPROVED:
            raise ApprovalRequiredError(
                f"session {session_id} has no APPROVED approval record",
                details={
                    "session_id": session_id,
                    "decision": record.decision.value if record and record.decision else None,
                },
            )
        if record.consumed_at is not None:
            raise ApprovalAlreadyConsumedError(
                f"the approval for session {session_id} has already been used",
                details={"session_id": session_id, "consumed_at": record.consumed_at.isoformat()},
            )
        return ApprovalRecord.model_validate(record)

    async def consume(self, session_id: str) -> None:
        """Mark the approval used. Called once, by `PRService` after the PR opens."""
        await self.assert_approved(session_id)
        self._approvals.consume(session_id)
        logger.info("approval for session %s consumed", session_id)

    def _require_session(self, session_id: str) -> None:
        if self._sessions.get_by_id(session_id) is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
