"""`RepoIngestionService` — `{repo_url, issue}` → an isolated workspace plus a
navigable index (E4-F2).

Orchestration only. Each step emits an `INGESTION_STEP` event so a run is replayable;
any failure is normalised to `RepositoryIngestionError` and recorded as
`SESSION_FAILED` before it propagates. This service does not change session status —
that is the orchestrator's job (E7); here it only records the ingestion facts on the
session row.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from devmind.core.constants import REPO_TREE_MAX_DEPTH, REPO_TREE_MAX_ENTRIES
from devmind.core.enums import EventType, IngestionStep
from devmind.exceptions import GitHubError, RepositoryIngestionError, SessionNotFoundError
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.github import IssueRead
from devmind.schemas.repo import IngestionResult
from devmind.schemas.session import SessionRead
from devmind.services.code_index_service import CodeIndexService
from devmind.services.git_repository_cloner import GitRepositoryCloner
from devmind.services.github_client import GitHubClient
from devmind.services.repo_brief_builder import RepoBriefBuilder
from devmind.services.repo_profiler import RepoProfiler
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class RepoIngestionService:
    """Turns a created session into a ready-to-work workspace."""

    def __init__(
        self,
        workspaces: WorkspaceManager,
        github: GitHubClient,
        cloner: GitRepositoryCloner,
        profiler: RepoProfiler,
        code_index: CodeIndexService,
        symbol_indexer: SymbolIndexer,
        brief_builder: RepoBriefBuilder,
        sessions: SessionRepository,
        events: EventRepository,
    ) -> None:
        self._workspaces = workspaces
        self._github = github
        self._cloner = cloner
        self._profiler = profiler
        self._code_index = code_index
        self._symbol_indexer = symbol_indexer
        self._brief_builder = brief_builder
        self._sessions = sessions
        self._events = events

    async def ingest(self, session_id: str) -> IngestionResult:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        session = SessionRead.model_validate(model)
        try:
            return await self._ingest(session)
        except RepositoryIngestionError as exc:
            self._events.append(
                session.id,
                EventType.SESSION_FAILED,
                {"stage": "ingestion", "error": exc.message},
            )
            logger.warning("ingestion failed for session %s: %s", session.id, exc.message)
            raise

    async def _ingest(self, session: SessionRead) -> IngestionResult:
        workspace = self._workspaces.create(session.id)
        self._emit(session.id, IngestionStep.WORKSPACE_CREATED, {"path": str(workspace)})

        await self._cloner.clone(session.repo_url, workspace)
        base_commit_sha = await self._cloner.base_commit_sha(workspace)
        default_branch = await self._cloner.default_branch(workspace)
        self._emit(
            session.id,
            IngestionStep.CLONED,
            {"base_commit_sha": base_commit_sha, "default_branch": default_branch},
        )

        issue = await self._resolve_issue(session.repo_url, session.issue_number)
        issue_title = issue.title if issue is not None else session.issue_title
        issue_body = issue.body if issue is not None else session.issue_body
        self._emit(
            session.id,
            IngestionStep.ISSUE_RESOLVED,
            {"issue_number": session.issue_number, "fetched": issue is not None},
        )

        profile = self._profiler.profile(workspace)
        self._emit(
            session.id,
            IngestionStep.PROFILED,
            {
                "language": profile.language,
                "test_framework": profile.test_framework.value if profile.test_framework else None,
                "has_test_suite": profile.has_test_suite,
            },
        )

        file_tree = self._code_index.build_tree(
            workspace, max_depth=REPO_TREE_MAX_DEPTH, max_entries=REPO_TREE_MAX_ENTRIES
        )
        symbol_index = self._symbol_indexer.index(workspace)
        brief = self._brief_builder.build(
            repo_url=session.repo_url,
            profile=profile,
            file_tree=file_tree,
            symbol_index=symbol_index,
            root=workspace,
        )
        self._emit(
            session.id,
            IngestionStep.INDEXED,
            {
                "modules": len(symbol_index.modules),
                "skipped": len(symbol_index.skipped),
                "tree_truncated": file_tree.truncated,
            },
        )

        self._sessions.record_ingestion(
            session.id,
            base_commit_sha=base_commit_sha,
            default_branch=default_branch,
            workspace_path=str(workspace),
            has_test_suite=profile.has_test_suite,
            issue_title=issue_title,
            issue_body=issue_body,
        )

        return IngestionResult(
            session_id=session.id,
            workspace_path=str(workspace),
            base_commit_sha=base_commit_sha,
            default_branch=default_branch,
            profile=profile,
            brief=brief,
            symbol_index=symbol_index,
            file_tree=file_tree,
            issue=issue,
        )

    async def _resolve_issue(self, repo_url: str, issue_number: int | None) -> IssueRead | None:
        if issue_number is None:
            return None
        try:
            return await self._github.fetch_issue(repo_url, issue_number)
        except GitHubError as exc:
            raise RepositoryIngestionError(
                f"issue #{issue_number} could not be fetched: {exc.message}",
                details={"issue_number": issue_number},
            ) from exc

    def _emit(self, session_id: str, step: IngestionStep, detail: Mapping[str, object]) -> None:
        self._events.append(
            session_id, EventType.INGESTION_STEP, {"step": step.value, **dict(detail)}
        )
