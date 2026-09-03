"""`SessionService` — the use-case layer the API routers delegate to (E11-F1).

Routers translate HTTP to a call here and a schema back; every rule about *what* a
session can do lives in this layer or below it (`SessionStateMachine`,
`ApprovalService`). Nothing here raises `HTTPException` — only `DevMindError`
subclasses, which `api/errors.py` maps to RFC-7807 (Claude.md §1).

One `SessionService` is built per request, over a request-scoped repository set. The
long-running orchestration a `POST /sessions` schedules is *not* this object's job —
that is `SessionRunner`, which opens its own unit-of-work scope.
"""

from __future__ import annotations

import logging

from devmind.core.constants import (
    API_DEFAULT_PAGE_LIMIT,
    API_MAX_PAGE_LIMIT,
    DIFF_ENDPOINT_TIMEOUT_SECONDS,
    NON_INTERACTIVE_GIT_ENV,
)
from devmind.core.enums import EventType, SessionStatus
from devmind.exceptions import (
    InvalidStateTransitionError,
    RecordNotFoundError,
    SessionNotFoundError,
)
from devmind.interfaces.command_runner import CommandRunner
from devmind.models.session import SessionModel
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.approval import ApprovalDecisionRequest, ApprovalRead, ApprovalRequest
from devmind.schemas.event import EventRead
from devmind.schemas.session import SessionCreate, SessionRead, SessionSummary
from devmind.services.approval_service import ApprovalService
from devmind.services.review_payload_service import ReviewPayloadService
from devmind.services.session_state_machine import SessionStateMachine

logger = logging.getLogger(__name__)


class SessionService:
    """Create, read, list, cancel; plus the approval-gate calls a router forwards."""

    def __init__(
        self,
        sessions: SessionRepository,
        events: EventRepository,
        state: SessionStateMachine,
        approvals: ApprovalService,
        review: ReviewPayloadService,
        runner: CommandRunner,
    ) -> None:
        self._sessions = sessions
        self._events = events
        self._state = state
        self._approvals = approvals
        self._review = review
        self._runner = runner

    # --- lifecycle -----------------------------------------------------------

    def create(self, data: SessionCreate) -> SessionRead:
        """Persist a new `CREATED` session and record `SESSION_CREATED`."""
        model = self._sessions.create(data)
        self._events.append(
            model.id,
            EventType.SESSION_CREATED,
            {
                "repo_url": model.repo_url,
                "issue_number": model.issue_number,
                "has_issue_text": model.issue_body is not None,
            },
        )
        logger.info("session %s created for %s", model.id, model.repo_url)
        return SessionRead.model_validate(model)

    def get(self, session_id: str) -> SessionRead:
        return SessionRead.model_validate(self._require(session_id))

    def list_summaries(
        self,
        *,
        status: SessionStatus | None = None,
        limit: int = API_DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> list[SessionSummary]:
        capped = max(1, min(limit, API_MAX_PAGE_LIMIT))
        rows = self._sessions.list(status=status, limit=capped, offset=max(0, offset))
        return [SessionSummary.model_validate(row) for row in rows]

    def events(
        self, session_id: str, *, after_sequence: int = 0, limit: int = API_MAX_PAGE_LIMIT
    ) -> list[EventRead]:
        self._require(session_id)
        capped = max(1, min(limit, API_MAX_PAGE_LIMIT))
        rows = self._events.list_since(session_id, max(0, after_sequence), limit=capped)
        return [EventRead.model_validate(row) for row in rows]

    def cancel(self, session_id: str) -> SessionRead:
        """Cooperative cancel — move the session to `HALTED`; a running loop observes
        it at the top of its next step. Raises `InvalidStateTransitionError` (409) if
        the session is already terminal or past the point cancellation means anything.
        """
        self._require(session_id)
        updated = self._state.transition(
            session_id, SessionStatus.HALTED, reason="cancelled by operator"
        )
        logger.info("session %s cancelled by operator", session_id)
        return updated

    async def diff(self, session_id: str) -> str:
        """The working-tree diff as `git` reports it on the host. Raises
        `RecordNotFoundError` (404) if the session has no workspace yet.
        """
        model = self._require(session_id)
        if not model.workspace_path:
            raise RecordNotFoundError(
                f"session {session_id} has no workspace yet — no diff to show",
                details={"session_id": session_id, "status": model.status.value},
            )
        result = await self._runner.run(
            ["git", "-C", model.workspace_path, "diff"],
            env=NON_INTERACTIVE_GIT_ENV,
            timeout=DIFF_ENDPOINT_TIMEOUT_SECONDS,
        )
        return result.stdout

    # --- approval gate -----------------------------------------------------

    async def approval_request(self, session_id: str) -> ApprovalRequest:
        """The human-review payload. 409 unless the session is `AWAITING_APPROVAL`."""
        model = self._require(session_id)
        if model.status is not SessionStatus.AWAITING_APPROVAL:
            raise InvalidStateTransitionError(
                f"session {session_id} is {model.status.value}, not awaiting approval — "
                "there is no review payload to fetch",
                details={"session_id": session_id, "status": model.status.value},
            )
        return await self._review.build(session_id)

    async def decide(self, session_id: str, request: ApprovalDecisionRequest) -> ApprovalRead:
        """Record the human's verdict. Delegates every rule to `ApprovalService`."""
        self._require(session_id)
        record = await self._approvals.decide(
            session_id,
            request.decision,
            decided_by=request.decided_by,
            reason=request.reason,
        )
        return ApprovalRead.model_validate(record)

    # --- internals -------------------------------------------------------

    def _require(self, session_id: str) -> SessionModel:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        return model
