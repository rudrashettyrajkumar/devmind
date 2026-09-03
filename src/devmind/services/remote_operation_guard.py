"""`RemoteOperationGuard` — safety layer 3, the guard clause (E9-F3-T1).

Every remote-capable call in E10 goes through `authorize()` first, as its **first
statement**. The guard re-reads the approval record from the database through
`ApprovalService` rather than trusting anything the caller passes in — so a bug or a
refactor upstream that lets an unapproved session reach `PRService` still hits a
closed door here (design §9).

This is one of three independent layers, all kept:

1. capability separation — the agent has no remote tool at all (SI-1);
2. state machine — `PR_OPENED` is reachable only from `APPROVED` (SI-3, layer 2);
3. this guard — the record is re-read and re-checked at the point of use.

There is no setting, flag, or environment that disables it.
"""

from __future__ import annotations

import logging

from devmind.schemas.approval import ApprovalRecord
from devmind.services.approval_service import ApprovalService

logger = logging.getLogger(__name__)


class RemoteOperationGuard:
    """The only door to a remote operation."""

    def __init__(self, approvals: ApprovalService) -> None:
        self._approvals = approvals

    async def authorize(self, session_id: str, operation: str) -> ApprovalRecord:
        """Return the live `APPROVED`, unconsumed record, or raise.

        Raises `ApprovalRequiredError` unless the session has a persisted `APPROVED`
        approval, and `ApprovalAlreadyConsumedError` if the token has been spent.
        """
        record = await self._approvals.assert_approved(session_id)
        logger.info(
            "remote operation %r authorized for session %s (approval %s)",
            operation,
            session_id,
            record.id,
        )
        return record
