"""`PRService` — the only path in DevMind that reaches a git remote (E10-F2).

`open_draft_pr()` is gated: `RemoteOperationGuard.authorize()` is its **first
statement**, before any validation, any log line, any repository read. The safety
suite asserts that an unapproved session produces zero git invocations, which only
holds if nothing runs ahead of that guard.

After the guard, in the order the spec fixes:

1. create the branch;
2. stage and commit (conventional subject + `Approved-by` / `Co-Authored-By` trailers);
3. `push` — the gated call;
4. render the PR body (`pr_body.md` + a deterministic provenance footer);
5. `gh pr create --draft`;
6. persist the `PullRequestModel`, emit `PR_OPENED`, transition `APPROVED → PR_OPENED`;
7. `approvals.consume()` — the single-use token is now spent (SI-4).

Any delivery failure moves the session to `FAILED` with the branch retained locally
and the error re-raised. Nothing is ever retried against the remote — a failed push
is a human's decision, not a loop's (spec §"Failure handling").

`settings.dry_run` short-circuits every remote step: the intended argv is logged, a
synthetic `PullRequestRead` is returned, and nothing is persisted or transitioned —
which makes the whole delivery path demonstrable with no repository.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from devmind.core.config import Settings
from devmind.core.constants import (
    COMMIT_SUBJECT_MAX_CHARS,
    COMMIT_SUBJECT_PREFIX,
    DEFAULT_BASE_BRANCH,
)
from devmind.core.enums import EventType, SessionStatus
from devmind.exceptions import (
    DevMindError,
    GitDeliveryError,
    GitHubError,
    SessionNotFoundError,
    WorkspaceError,
)
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.pull_request_repository import PullRequestRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.approval import ApprovalRecord, ApprovalRequest
from devmind.schemas.pull_request import CommitMessage, PullRequestRead
from devmind.schemas.session import SessionRead
from devmind.services.approval_request_builder import ApprovalRequestBuilder
from devmind.services.approval_service import ApprovalService
from devmind.services.branch_namer import BranchNamer
from devmind.services.git_service import GitService
from devmind.services.github_client import GitHubClient
from devmind.services.pr_body_composer import PrBodyComposer
from devmind.services.remote_operation_guard import RemoteOperationGuard
from devmind.services.session_state_machine import SessionStateMachine

logger = logging.getLogger(__name__)

_OPERATION: Final[str] = "open_draft_pr"


class PRService:
    """Delivers one approved session as a draft pull request."""

    def __init__(
        self,
        guard: RemoteOperationGuard,
        review: ApprovalRequestBuilder,
        git: GitService,
        github: GitHubClient,
        body: PrBodyComposer,
        branch_namer: BranchNamer,
        prs: PullRequestRepository,
        sessions: SessionRepository,
        events: EventRepository,
        state: SessionStateMachine,
        approvals: ApprovalService,
        settings: Settings,
    ) -> None:
        self._guard = guard
        self._review = review
        self._git = git
        self._github = github
        self._body = body
        self._branch_namer = branch_namer
        self._prs = prs
        self._sessions = sessions
        self._events = events
        self._state = state
        self._approvals = approvals
        self._settings = settings

    async def open_draft_pr(self, session_id: str) -> PullRequestRead:
        approval = await self._guard.authorize(session_id, _OPERATION)  # ← FIRST STATEMENT

        session = self._require_session(session_id)
        workspace = self._require_workspace(session)
        review = await self._review.build(session_id)

        taken = await self._git.list_remote_branches(workspace)
        branch = self._branch_namer.build(
            session.issue_number,
            session.issue_title or session.issue_body or "apply approved change",
            taken=taken,
        )
        message = self._commit_message(session, review, approval)
        base = session.default_branch or DEFAULT_BASE_BRANCH

        # Rendered before any git write: a bad model response (missing section,
        # provider error) then aborts with zero remote operations, leaving the
        # session APPROVED and retryable rather than half-delivered.
        pr_body = await self._body.compose(
            session=session,
            review=review,
            approval=approval,
            model=self._settings.agent_model,
            max_fix_attempts=self._settings.max_fix_attempts,
        )

        try:
            await self._git.create_branch(workspace, branch)
            await self._git.stage_all(workspace)
            head_sha = await self._git.commit(workspace, message)
            await self._git.push(workspace, branch)  # GATED
            draft = await self._github.create_draft_pr(
                session.repo_url,
                base=base,
                head=branch,
                title=message.subject,
                body=pr_body,
                dry_run=self._settings.dry_run,
            )
        except (GitDeliveryError, GitHubError) as exc:
            self._mark_failed(session_id, exc)
            raise

        if self._settings.dry_run:
            logger.info(
                "dry-run: session %s stays APPROVED, no PR persisted (branch would be %s)",
                session_id,
                branch,
            )
            return PullRequestRead(
                id="dry-run",
                session_id=session_id,
                number=draft.number,
                url=draft.url,
                branch=branch,
                head_sha=head_sha,
                created_at=datetime.now(UTC),
                dry_run=True,
            )

        pr = self._prs.create(
            session_id,
            number=draft.number,
            url=draft.url,
            branch=branch,
            head_sha=head_sha,
        )
        self._events.append(
            session_id,
            EventType.PR_OPENED,
            {
                "pr_number": draft.number,
                "url": draft.url,
                "branch": branch,
                "head_sha": head_sha,
            },
        )
        self._state.transition(session_id, SessionStatus.PR_OPENED)
        await self._approvals.consume(session_id)
        logger.info(
            "session %s delivered as draft PR #%s (%s)", session_id, draft.number, draft.url
        )
        return PullRequestRead.model_validate(pr)

    # --- helpers ---------------------------------------------------------

    def _require_session(self, session_id: str) -> SessionRead:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        return SessionRead.model_validate(model)

    @staticmethod
    def _require_workspace(session: SessionRead) -> Path:
        if not session.workspace_path:
            raise WorkspaceError(
                f"session {session.id} has no workspace — nothing to deliver",
                details={"session_id": session.id},
            )
        return Path(session.workspace_path)

    def _commit_message(
        self, session: SessionRead, review: ApprovalRequest, approval: ApprovalRecord
    ) -> CommitMessage:
        return CommitMessage(
            subject=self._subject(session),
            body=review.issue_understanding,
            issue_number=session.issue_number,
            session_id=session.id,
            approved_by=approval.decided_by or "an authorized reviewer",
        )

    @staticmethod
    def _subject(session: SessionRead) -> str:
        raw = (session.issue_title or session.issue_body or "").strip()
        first_line = raw.splitlines()[0].strip() if raw else ""
        description = (
            (first_line[:1].lower() + first_line[1:])
            if first_line
            else ("apply the approved change")
        )
        description = description.rstrip(". ")
        subject = f"{COMMIT_SUBJECT_PREFIX}{description}"
        if len(subject) > COMMIT_SUBJECT_MAX_CHARS:
            subject = subject[:COMMIT_SUBJECT_MAX_CHARS].rstrip(" ").rstrip("-") + "…"
        return subject

    def _mark_failed(self, session_id: str, exc: DevMindError) -> None:
        reason = exc.reason if isinstance(exc, GitDeliveryError) else None
        model = self._sessions.get_by_id(session_id)
        if model is not None and model.status.can_transition_to(SessionStatus.FAILED):
            self._state.transition(session_id, SessionStatus.FAILED, reason=exc.message)
        self._events.append(
            session_id,
            EventType.SESSION_FAILED,
            {
                "error": exc.message,
                "type": type(exc).__name__,
                "reason": reason.value if reason is not None else None,
            },
        )
        logger.warning("session %s: PR delivery failed (%s)", session_id, exc.message)
