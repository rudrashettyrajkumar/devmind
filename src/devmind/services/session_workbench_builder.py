"""`SessionWorkbenchBuilder` — the production `WorkbenchBuilder` (E7-F3).

Resolves and starts the sandbox, best-effort installs the repo's dependencies (a
failure there is logged, not fatal — the editing phase can still make and review a
change), and wires the full tool registry to a `ToolContext` for the workspace.
"""

from __future__ import annotations

import logging
from pathlib import Path

from devmind.exceptions import SandboxError
from devmind.interfaces.workbench_builder import WorkbenchBuilder
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.repo import IngestionResult
from devmind.schemas.session import SessionRead
from devmind.services.code_search_service import CodeSearchService
from devmind.services.sandbox_factory import SandboxFactory
from devmind.services.session_workbench import SessionWorkbench
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.workspace_path_guard import WorkspacePathGuard
from devmind.tools.tool_context import ToolContext
from devmind.tools.tool_suite import build_tool_registry

logger = logging.getLogger(__name__)


class SessionWorkbenchBuilder(WorkbenchBuilder):
    """Builds a real, sandboxed workbench from an ingestion result."""

    def __init__(
        self,
        sandbox_factory: SandboxFactory,
        search: CodeSearchService,
        indexer: SymbolIndexer,
        todos: TodoRepository,
        events: EventRepository,
    ) -> None:
        self._sandbox_factory = sandbox_factory
        self._search = search
        self._indexer = indexer
        self._todos = todos
        self._events = events

    async def build(self, session: SessionRead, ingestion: IngestionResult) -> SessionWorkbench:
        workspace = Path(ingestion.workspace_path)
        sandbox = self._sandbox_factory.create()
        await sandbox.setup(workspace)
        try:
            install = await sandbox.install_dependencies(ingestion.profile)
            if not install.succeeded:
                logger.warning(
                    "dependency install exited %d for session %s; continuing",
                    install.exit_code,
                    session.id,
                )
        except SandboxError as exc:
            logger.warning(
                "dependency install failed for session %s: %s; continuing",
                session.id,
                exc.message,
            )

        registry = build_tool_registry(search=self._search, indexer=self._indexer)
        tool_context = ToolContext(
            session_id=session.id,
            workspace=workspace,
            guard=WorkspacePathGuard(workspace),
            sandbox=sandbox,
            profile=ingestion.profile,
            todos=self._todos,
            events=self._events,
        )
        return SessionWorkbench(tool_context=tool_context, registry=registry, sandbox=sandbox)
