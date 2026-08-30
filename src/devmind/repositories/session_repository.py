"""Data access for the session aggregate. No business rules live here — deciding
whether a status transition is legal is `SessionStatus.can_transition_to()`'s job
(core/enums.py) and `SessionStateMachine`'s to enforce (services/); this repository
writes whatever status it is told.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from devmind.core.enums import SessionStatus
from devmind.exceptions import SessionNotFoundError
from devmind.models.base import utcnow
from devmind.models.session import SessionModel
from devmind.schemas.session import SessionCreate


class SessionRepository:
    """CRUD and usage accounting for `SessionModel`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: SessionCreate) -> SessionModel:
        """`issue_description`, when given instead of `issue_number`, becomes the
        initial `issue_body` — the whole problem statement until (if ever) ingestion
        (E4) has a real issue to fetch from GitHub. See `SessionModel`'s docstring.
        """
        model = SessionModel(
            repo_url=data.repo_url,
            issue_number=data.issue_number,
            issue_title=None,
            issue_body=data.issue_description,
            status=SessionStatus.CREATED,
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def get_by_id(self, session_id: str) -> SessionModel | None:
        return self._session.get(SessionModel, session_id)

    def list(
        self, *, status: SessionStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[SessionModel]:
        stmt = select(SessionModel).order_by(SessionModel.created_at.desc())
        if status is not None:
            stmt = stmt.where(SessionModel.status == status)
        stmt = stmt.limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())

    def update_status(
        self, session_id: str, status: SessionStatus, *, failure_reason: str | None = None
    ) -> SessionModel:
        model = self._get_or_raise(session_id)
        model.status = status
        if failure_reason is not None:
            model.failure_reason = failure_reason
        if status.is_terminal():
            model.completed_at = utcnow()
        self._session.commit()
        self._session.refresh(model)
        return model

    def record_usage(
        self,
        session_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cost_usd: float,
    ) -> None:
        """Takes plain token counts rather than an `LLMResponse`/`TokenUsage` object —
        that schema doesn't exist until E3 (`schemas/llm.py`), and this repository
        must not depend forward on a later epic. `AnthropicProvider` (E3) unpacks its
        own `TokenUsage` into these fields when it calls this.
        """
        model = self._get_or_raise(session_id)
        model.input_tokens += input_tokens
        model.output_tokens += output_tokens
        model.cache_read_tokens += cache_read_tokens
        model.estimated_cost_usd += cost_usd
        self._session.commit()

    def record_ingestion(
        self,
        session_id: str,
        *,
        base_commit_sha: str,
        default_branch: str,
        workspace_path: str,
        has_test_suite: bool,
        issue_title: str | None = None,
        issue_body: str | None = None,
    ) -> SessionModel:
        """Persist what `RepoIngestionService` (E4) learned: the pinned revision, the
        workspace location, whether the repo ships a test suite, and — when the
        session was created from an issue number — the fetched issue title/body.

        `has_test_suite=False` is written through unchanged: E8 and E9 both branch on
        it, so a repo with no tests must not silently look like one that has them.
        """
        model = self._get_or_raise(session_id)
        model.base_commit_sha = base_commit_sha
        model.default_branch = default_branch
        model.workspace_path = workspace_path
        model.has_test_suite = has_test_suite
        if issue_title is not None:
            model.issue_title = issue_title
        if issue_body is not None:
            model.issue_body = issue_body
        self._session.commit()
        self._session.refresh(model)
        return model

    def increment_fix_attempts(self, session_id: str) -> int:
        model = self._get_or_raise(session_id)
        model.fix_attempts += 1
        self._session.commit()
        self._session.refresh(model)
        return model.fix_attempts

    def _get_or_raise(self, session_id: str) -> SessionModel:
        model = self.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        return model
