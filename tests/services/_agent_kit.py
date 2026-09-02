"""Shared builders for the E7 agent-loop / orchestrator tests.

Not a test module (leading underscore, no `test_` prefix) — pytest never collects it.
Everything here is deterministic: a `FakeLLMProvider` script in, an assertable
`AgentContext` / `LoopOutcome` out, no network and no real sandbox.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import AGENT_CONTEXT_WINDOW_TOKENS, MAX_FIX_ATTEMPTS
from devmind.core.enums import TOOLS_BY_PHASE, AgentPhase
from devmind.interfaces.llm_provider import LLMProvider
from devmind.interfaces.sandbox import Sandbox
from devmind.prompts.loader import PromptLoader
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.repo import RepoProfile
from devmind.services.agent_context import AgentContext
from devmind.services.agent_loop import AgentLoop
from devmind.services.code_search_service import CodeSearchService
from devmind.services.context_compactor import ContextCompactor
from devmind.services.cost_calculator import CostCalculator
from devmind.services.output_truncator import OutputTruncator
from devmind.services.planner_service import PlannerService
from devmind.services.pytest_output_parser import PytestOutputParser
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.self_correction_controller import SelfCorrectionController
from devmind.services.session_orchestrator import SessionOrchestrator
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.test_execution_service import TestExecutionService
from devmind.services.tool_executor import ToolExecutor
from devmind.services.tool_registry import ToolRegistry
from devmind.services.workspace_path_guard import WorkspacePathGuard
from devmind.tools.tool_context import ToolContext
from devmind.tools.tool_suite import build_tool_registry
from tests.fakes.fake_command_runner import FakeCommandRunner
from tests.fakes.fake_sandbox import FakeSandbox
from tests.fakes.fake_workbench_builder import FakeWorkbenchBuilder

_MODEL = "claude-opus-5"


def full_registry() -> ToolRegistry:
    return build_tool_registry(
        search=CodeSearchService(FakeCommandRunner()), indexer=SymbolIndexer()
    )


def make_tool_context(
    db_session: SQLAlchemySession, workspace: Path, session_id: str, sandbox: FakeSandbox
) -> ToolContext:
    return ToolContext(
        session_id=session_id,
        workspace=workspace,
        guard=WorkspacePathGuard(workspace),
        sandbox=sandbox,
        profile=RepoProfile(
            language="python", test_command=("python", "-m", "pytest"), has_test_suite=True
        ),
        todos=TodoRepository(db_session),
        events=EventRepository(db_session),
    )


def make_loop(
    llm: LLMProvider,
    db_session: SQLAlchemySession,
    registry: ToolRegistry,
    *,
    cost_ceiling_usd: float = 5.0,
    max_context_tokens: int = AGENT_CONTEXT_WINDOW_TOKENS,
) -> AgentLoop:
    events = EventRepository(db_session)
    return AgentLoop(
        llm,
        ToolExecutor(registry, events, OutputTruncator(2_000)),
        events,
        ContextCompactor(max_context_tokens=max_context_tokens),
        CostCalculator(),
        SessionRepository(db_session),
        model=_MODEL,
        cost_ceiling_usd=cost_ceiling_usd,
    )


def make_context(
    registry: ToolRegistry,
    session_id: str,
    phase: AgentPhase,
    *,
    step_budget: int = 10,
    system: str = "SYSTEM PREFIX",
    instruction: str = "Do the phase.",
) -> AgentContext:
    ctx = AgentContext(
        session_id=session_id,
        system=system,
        tools=registry.subset(TOOLS_BY_PHASE[phase]).to_api_schemas(),
        step_budget=step_budget,
    )
    ctx.add_user_message(instruction)
    return ctx


def build_orchestrator(
    db_session: SQLAlchemySession,
    *,
    ingestion: RepoIngestionService,
    loop_llm: LLMProvider,
    planner_llm: LLMProvider,
    sandbox: FakeSandbox,
    step_budget: int = 8,
    max_fix_attempts: int = MAX_FIX_ATTEMPTS,
) -> tuple[SessionOrchestrator, FakeWorkbenchBuilder]:
    """Wire a `SessionOrchestrator` with a real planner + loop (both driven by
    `FakeLLMProvider`) and fake ingestion + workbench. Returns the orchestrator and
    the workbench builder so a test can inspect what it built.
    """
    session_repo = SessionRepository(db_session)
    event_repo = EventRepository(db_session)
    test_runs = TestRunRepository(db_session)
    planner = PlannerService(planner_llm, PromptLoader(), TodoRepository(db_session), event_repo)
    loop = make_loop(loop_llm, db_session, full_registry())
    workbench_builder = FakeWorkbenchBuilder(sandbox, db_session)
    parser = PytestOutputParser()

    def make_test_execution(sb: Sandbox) -> TestExecutionService:
        return TestExecutionService(sb, parser, test_runs, event_repo)

    orchestrator = SessionOrchestrator(
        session_repo,
        SessionStateMachine(session_repo, event_repo),
        ingestion,
        planner,
        loop,
        workbench_builder,
        event_repo,
        PromptLoader(),
        make_test_execution,
        SelfCorrectionController(test_runs, event_repo, max_attempts=max_fix_attempts),
        step_budget=step_budget,
        max_fix_attempts=max_fix_attempts,
    )
    return orchestrator, workbench_builder
