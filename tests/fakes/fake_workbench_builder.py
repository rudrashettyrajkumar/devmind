"""Test doubles for the E7 orchestration seam: a `WorkbenchBuilder` that hands back a
`FakeSandbox`-backed workbench, and a `RepoIngestionService` stand-in that returns a
canned `IngestionResult` (or raises) without touching git or the network.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import PYTEST_MODULE_INVOCATION
from devmind.exceptions import RepositoryIngestionError
from devmind.interfaces.workbench_builder import WorkbenchBuilder
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.repo import (
    FileTree,
    FileTreeNode,
    IngestionResult,
    RepoBrief,
    RepoProfile,
    SymbolIndex,
)
from devmind.schemas.session import SessionRead
from devmind.services.code_search_service import CodeSearchService
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.session_workbench import SessionWorkbench
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.workspace_path_guard import WorkspacePathGuard
from devmind.tools.tool_context import ToolContext
from devmind.tools.tool_suite import build_tool_registry
from tests.fakes.fake_command_runner import FakeCommandRunner
from tests.fakes.fake_sandbox import FakeSandbox


def make_repo_profile() -> RepoProfile:
    return RepoProfile(
        language="python",
        test_command=PYTEST_MODULE_INVOCATION,
        has_test_suite=True,
    )


def make_repo_brief(repo_name: str = "sample") -> RepoBrief:
    return RepoBrief(
        repo_name=repo_name,
        language="python",
        test_framework=None,
        test_command=PYTEST_MODULE_INVOCATION,
        tree_preview="src/\n  sample/\n    calc.py\ntests/\n",
        key_modules=("src/sample/calc.py",),
        entry_points=(),
    )


def make_ingestion_result(session_id: str, workspace: Path) -> IngestionResult:
    return IngestionResult(
        session_id=session_id,
        workspace_path=str(workspace),
        base_commit_sha="0" * 40,
        default_branch="main",
        profile=make_repo_profile(),
        brief=make_repo_brief(),
        symbol_index=SymbolIndex(),
        file_tree=FileTree(root=FileTreeNode(name="", is_dir=True), entry_count=0),
        issue=None,
    )


class FakeRepoIngestionService(RepoIngestionService):
    """Returns a fixed `IngestionResult`, or raises `RepositoryIngestionError`.

    Subclasses the real service (so the type checks) but bypasses its constructor —
    it has no collaborators here.
    """

    def __init__(self, result: IngestionResult | None = None, *, raises: str | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[str] = []

    async def ingest(self, session_id: str) -> IngestionResult:
        self.calls.append(session_id)
        if self._raises is not None:
            raise RepositoryIngestionError(self._raises, details={"session_id": session_id})
        assert self._result is not None, "FakeRepoIngestionService needs a result or a raise"
        return self._result


class FakeWorkbenchBuilder(WorkbenchBuilder):
    """Builds a `SessionWorkbench` around a caller-supplied `FakeSandbox` and a real,
    fully-populated `ToolRegistry` (search/index tools wired to fakes).
    """

    def __init__(self, sandbox: FakeSandbox, db_session: SQLAlchemySession) -> None:
        self._sandbox = sandbox
        self._db_session = db_session
        self.built: list[str] = []

    async def build(self, session: SessionRead, ingestion: IngestionResult) -> SessionWorkbench:
        self.built.append(session.id)
        workspace = Path(ingestion.workspace_path)
        await self._sandbox.setup(workspace)
        registry = build_tool_registry(
            search=CodeSearchService(FakeCommandRunner()),
            indexer=SymbolIndexer(),
        )
        tool_context = ToolContext(
            session_id=session.id,
            workspace=workspace,
            guard=WorkspacePathGuard(workspace),
            sandbox=self._sandbox,
            profile=ingestion.profile,
            todos=TodoRepository(self._db_session),
            events=EventRepository(self._db_session),
        )
        return SessionWorkbench(tool_context=tool_context, registry=registry, sandbox=self._sandbox)
