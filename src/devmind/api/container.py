"""`Container` — the one place the object graph is composed (E11-F1).

A plain class, not a DI framework: the graph is a few dozen nodes and a framework
would be infrastructure with no requirement behind it (Claude.md §9). It also makes
`app.dependency_overrides` trivial in tests — every router dep resolves through a
method here.

Two kinds of node:

* **Singletons** — stateless or process-wide: the settings, the database manager, the
  prompt loader, the sandbox factory, the LLM provider, the host command runner, the
  tool registry, the event-stream service, the session runner.
* **Per-unit-of-work** — anything that holds a repository, and therefore a
  `Session`: `session_service(db)`, `approval_service(db)`, and the orchestrator
  built inside `SessionRunner`'s own scope.
"""

from __future__ import annotations

from functools import cached_property

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.config import Settings
from devmind.core.constants import MAX_TOOL_RESULT_CHARS
from devmind.core.database import DatabaseManager
from devmind.interfaces.command_runner import CommandRunner
from devmind.interfaces.llm_provider import LLMProvider
from devmind.interfaces.sandbox import Sandbox
from devmind.prompts.loader import PromptLoader
from devmind.repositories.approval_repository import ApprovalRepository
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.services.agent_loop import AgentLoop
from devmind.services.anthropic_provider import AnthropicProvider
from devmind.services.approval_service import ApprovalService
from devmind.services.code_index_service import CodeIndexService
from devmind.services.code_search_service import CodeSearchService
from devmind.services.context_compactor import ContextCompactor
from devmind.services.cost_calculator import CostCalculator
from devmind.services.event_stream_service import EventStreamService
from devmind.services.git_repository_cloner import GitRepositoryCloner
from devmind.services.github_client import GitHubClient
from devmind.services.output_truncator import OutputTruncator
from devmind.services.planner_service import PlannerService
from devmind.services.pytest_output_parser import PytestOutputParser
from devmind.services.repo_brief_builder import RepoBriefBuilder
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.repo_profiler import RepoProfiler
from devmind.services.review_payload_service import ReviewPayloadService
from devmind.services.sandbox_factory import SandboxFactory
from devmind.services.self_correction_controller import SelfCorrectionController
from devmind.services.session_orchestrator import SessionOrchestrator
from devmind.services.session_runner import SessionRunner
from devmind.services.session_service import SessionService
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.session_workbench_builder import SessionWorkbenchBuilder
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.test_execution_service import TestExecutionService
from devmind.services.tool_executor import ToolExecutor
from devmind.services.tool_registry import ToolRegistry
from devmind.services.workspace_manager import WorkspaceManager
from devmind.tools.tool_suite import build_tool_registry


class Container:
    """Composes DevMind's runtime object graph from one `Settings` + `DatabaseManager`."""

    def __init__(self, settings: Settings, database: DatabaseManager) -> None:
        self._settings = settings
        self._database = database

    # --- exposed singletons ------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def database(self) -> DatabaseManager:
        return self._database

    @cached_property
    def prompt_loader(self) -> PromptLoader:
        return PromptLoader()

    @cached_property
    def command_runner(self) -> CommandRunner:
        return SubprocessCommandRunner()

    @cached_property
    def cost_calculator(self) -> CostCalculator:
        return CostCalculator()

    @cached_property
    def sandbox_factory(self) -> SandboxFactory:
        return SandboxFactory(self._settings)

    @cached_property
    def llm_provider(self) -> LLMProvider:
        return AnthropicProvider.from_settings(self._settings, self.cost_calculator)

    @cached_property
    def code_search(self) -> CodeSearchService:
        return CodeSearchService(self.command_runner)

    @cached_property
    def symbol_indexer(self) -> SymbolIndexer:
        return SymbolIndexer()

    @cached_property
    def tool_registry(self) -> ToolRegistry:
        return build_tool_registry(search=self.code_search, indexer=self.symbol_indexer)

    @cached_property
    def pytest_parser(self) -> PytestOutputParser:
        return PytestOutputParser()

    @cached_property
    def review_payload_service(self) -> ReviewPayloadService:
        return ReviewPayloadService(
            self._database,
            self.llm_provider,
            self.prompt_loader,
            self.command_runner,
            max_session_cost_usd=self._settings.max_session_cost_usd,
        )

    @cached_property
    def event_stream_service(self) -> EventStreamService:
        return EventStreamService(self._database)

    @cached_property
    def session_runner(self) -> SessionRunner:
        return SessionRunner(
            self._database,
            self.build_orchestrator,
            max_concurrent=self._settings.max_concurrent_sessions,
        )

    # --- per-unit-of-work factories -------------------------------------

    def session_service(self, db: SQLAlchemySession) -> SessionService:
        sessions = SessionRepository(db)
        events = EventRepository(db)
        state = SessionStateMachine(sessions, events)
        approvals = ApprovalService(ApprovalRepository(db), sessions, state, events)
        return SessionService(
            sessions, events, state, approvals, self.review_payload_service, self.command_runner
        )

    def approval_service(self, db: SQLAlchemySession) -> ApprovalService:
        sessions = SessionRepository(db)
        events = EventRepository(db)
        return ApprovalService(
            ApprovalRepository(db), sessions, SessionStateMachine(sessions, events), events
        )

    def build_orchestrator(self, db: SQLAlchemySession) -> SessionOrchestrator:
        """The full agent graph, bound to one unit-of-work `Session`."""
        sessions = SessionRepository(db)
        events = EventRepository(db)
        todos = TodoRepository(db)
        test_runs = TestRunRepository(db)
        state = SessionStateMachine(sessions, events)

        ingestion = RepoIngestionService(
            workspaces=WorkspaceManager(
                self._settings.workspace_root, max_bytes=self._settings.workspace_max_bytes
            ),
            github=GitHubClient(self.command_runner, token=self._settings.github_token),
            cloner=GitRepositoryCloner(self.command_runner),
            profiler=RepoProfiler(),
            code_index=CodeIndexService(),
            symbol_indexer=self.symbol_indexer,
            brief_builder=RepoBriefBuilder(),
            sessions=sessions,
            events=events,
        )
        planner = PlannerService(self.llm_provider, self.prompt_loader, todos, events)
        loop = AgentLoop(
            self.llm_provider,
            ToolExecutor(self.tool_registry, events, OutputTruncator(MAX_TOOL_RESULT_CHARS)),
            events,
            ContextCompactor(max_context_tokens=self._settings.agent_context_window_tokens),
            self.cost_calculator,
            sessions,
            model=self._settings.agent_model,
            cost_ceiling_usd=self._settings.max_session_cost_usd,
        )
        workbench_builder = SessionWorkbenchBuilder(
            self.sandbox_factory, self.code_search, self.symbol_indexer, todos, events
        )
        parser = self.pytest_parser

        def make_test_execution(sandbox: Sandbox) -> TestExecutionService:
            return TestExecutionService(sandbox, parser, test_runs, events)

        correction = SelfCorrectionController(
            test_runs, events, max_attempts=self._settings.max_fix_attempts
        )
        return SessionOrchestrator(
            sessions,
            state,
            ingestion,
            planner,
            loop,
            workbench_builder,
            events,
            self.prompt_loader,
            make_test_execution,
            correction,
            step_budget=self._settings.max_agent_steps_per_phase,
            max_fix_attempts=self._settings.max_fix_attempts,
        )
