"""`ReviewPayloadService` — assembles the E9 `ApprovalRequest` for the API (E11).

`ApprovalRequestBuilder` (E9) needs a `DiffService`, which needs a `Sandbox` bound to
the session's workspace — and that workspace is only known per request, after the run
has finished. This service does that late binding: it opens a unit-of-work scope,
resolves the workspace, wires `ApprovalRequestBuilder` over a `HostGitSandbox`, and
returns the payload. `SessionService` depends on this rather than on the builder
directly.
"""

from __future__ import annotations

from pathlib import Path

from devmind.core.database import DatabaseManager
from devmind.exceptions import SessionNotFoundError, WorkspaceError
from devmind.interfaces.command_runner import CommandRunner
from devmind.interfaces.llm_provider import LLMProvider
from devmind.prompts.loader import PromptLoader
from devmind.repositories.session_repository import SessionRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.approval import ApprovalRequest
from devmind.services.approval_request_builder import ApprovalRequestBuilder
from devmind.services.change_summary_service import ChangeSummaryService
from devmind.services.diff_service import DiffService
from devmind.services.host_git_sandbox import HostGitSandbox
from devmind.services.workspace_path_guard import WorkspacePathGuard


class ReviewPayloadService:
    """Builds one `ApprovalRequest`, wiring the E9 builder against the live workspace."""

    def __init__(
        self,
        database: DatabaseManager,
        llm: LLMProvider,
        prompts: PromptLoader,
        runner: CommandRunner,
        *,
        max_session_cost_usd: float,
    ) -> None:
        self._database = database
        self._llm = llm
        self._prompts = prompts
        self._runner = runner
        self._max_session_cost_usd = max_session_cost_usd

    async def build(self, session_id: str) -> ApprovalRequest:
        with self._database.session_scope() as db:
            sessions = SessionRepository(db)
            model = sessions.get_by_id(session_id)
            if model is None:
                raise SessionNotFoundError(
                    f"session {session_id} not found", details={"session_id": session_id}
                )
            if not model.workspace_path:
                raise WorkspaceError(
                    f"session {session_id} has no workspace — no review payload to build",
                    details={"session_id": session_id},
                )
            workspace = Path(model.workspace_path)
            diffs = DiffService(
                HostGitSandbox(workspace, self._runner), WorkspacePathGuard(workspace)
            )
            builder = ApprovalRequestBuilder(
                sessions,
                TodoRepository(db),
                TestRunRepository(db),
                ChangeSummaryService(self._llm, self._prompts, diffs),
                diffs,
                max_session_cost_usd=self._max_session_cost_usd,
            )
            return await builder.build(session_id)
