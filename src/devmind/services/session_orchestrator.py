"""`SessionOrchestrator` — drives the state machine from CREATED to TESTING (E7-F3).

Every status change goes through `SessionStateMachine.transition()`, never a direct
write, so the legal-transition map stays the single source of truth (design §9).

```
CREATED  → INGESTING      RepoIngestionService.ingest()
         → PLANNING        PlannerService.create_plan()
         → INVESTIGATING   AgentLoop.run(INVESTIGATION, read-only tools)
         → EDITING         AgentLoop.run(EDITING, write tools)
         → TESTING         handed to E8
```

Two phase-boundary invariants this class enforces:

* **Investigation** runs with a read-only tool subset and must end with a findings
  summary; that summary — not the transcript — is what crosses into editing.
* **Editing** must produce a non-empty `git diff`. An empty diff after editing is a
  failure: the agent believing it fixed something without touching a file is exactly
  the case this check exists for.

Any `DevMindError` ends the session `FAILED` with a `failure_reason` and a
`SESSION_FAILED` event. Cleanup runs in `finally`.
"""

from __future__ import annotations

import logging

from devmind.core.enums import (
    TOOLS_BY_PHASE,
    AgentPhase,
    EventType,
    LoopStatus,
    SessionStatus,
)
from devmind.exceptions import DevMindError, SessionNotFoundError
from devmind.interfaces.workbench_builder import WorkbenchBuilder
from devmind.prompts.loader import PromptLoader
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.agent import LoopOutcome
from devmind.schemas.repo import IngestionResult
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.session import SessionRead
from devmind.schemas.todo import TodoItemRead
from devmind.services.agent_context import AgentContext
from devmind.services.agent_loop import AgentLoop
from devmind.services.planner_service import PlannerService
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.session_workbench import SessionWorkbench

logger = logging.getLogger(__name__)


class SessionOrchestrator:
    """Runs one session through ingestion, planning, investigation, and editing."""

    def __init__(
        self,
        sessions: SessionRepository,
        state_machine: SessionStateMachine,
        ingestion: RepoIngestionService,
        planner: PlannerService,
        loop: AgentLoop,
        workbench_builder: WorkbenchBuilder,
        events: EventRepository,
        prompts: PromptLoader,
        *,
        step_budget: int,
    ) -> None:
        self._sessions = sessions
        self._state = state_machine
        self._ingestion = ingestion
        self._planner = planner
        self._loop = loop
        self._workbench_builder = workbench_builder
        self._events = events
        self._prompts = prompts
        self._step_budget = step_budget

    async def run(self, session_id: str) -> None:
        workbench: SessionWorkbench | None = None
        try:
            self._state.transition(session_id, SessionStatus.INGESTING)
            ingestion = await self._ingestion.ingest(session_id)

            self._state.transition(session_id, SessionStatus.PLANNING)
            session = self._load(session_id)
            plan = await self._planner.create_plan(session, ingestion.brief)
            plan_text = self._format_plan(plan)

            self._state.transition(session_id, SessionStatus.INVESTIGATING)
            session = self._load(session_id)
            workbench = await self._workbench_builder.build(session, ingestion)
            system = self._system_prefix(ingestion)

            investigation = await self._run_phase(
                AgentPhase.INVESTIGATION,
                session,
                workbench,
                system,
                plan_text=plan_text,
                instruction=self._prompts.render(
                    "investigation",
                    issue_title=self._issue_line(session),
                    todo_plan=plan_text,
                ),
            )
            if not self._phase_ok(AgentPhase.INVESTIGATION, investigation):
                return
            findings = (
                investigation.finish_summary
                or investigation.final_text
                or "(investigation produced no explicit findings summary)"
            )

            self._state.transition(session_id, SessionStatus.EDITING)
            editing = await self._run_phase(
                AgentPhase.EDITING,
                session,
                workbench,
                system,
                plan_text=plan_text,
                instruction=self._prompts.render(
                    "patch_author",
                    issue_title=self._issue_line(session),
                    findings=findings,
                    todo_plan=plan_text,
                ),
            )
            if not self._phase_ok(AgentPhase.EDITING, editing):
                return

            diff = await self._working_tree_diff(workbench)
            if not diff.strip():
                raise DevMindError(
                    f"the editing phase for session {session_id} produced no working-tree change",
                    details={"session_id": session_id, "phase": AgentPhase.EDITING.value},
                )

            self._state.transition(session_id, SessionStatus.TESTING)
            logger.info(
                "session %s reached TESTING (%d-char diff); handing off to E8",
                session_id,
                len(diff),
            )
        except DevMindError as exc:
            self._fail(session_id, exc)
        finally:
            if workbench is not None:
                await self._safe_cleanup(session_id, workbench)

    # --- phases ---------------------------------------------------------------

    async def _run_phase(
        self,
        phase: AgentPhase,
        session: SessionRead,
        workbench: SessionWorkbench,
        system: str,
        *,
        plan_text: str,
        instruction: str,
    ) -> LoopOutcome:
        """A fresh context per phase — system + brief + plan + this phase's
        instruction, never the previous phase's transcript (spec §checkpoint).
        """
        subset = workbench.registry.subset(TOOLS_BY_PHASE[phase])
        ctx = AgentContext(
            session_id=session.id,
            system=system,
            tools=subset.to_api_schemas(),
            step_budget=self._step_budget,
        )
        ctx.plan_text = plan_text
        ctx.add_user_message(instruction)
        return await self._loop.run(ctx, workbench.tool_context, phase)

    def _phase_ok(self, phase: AgentPhase, outcome: LoopOutcome) -> bool:
        """True to proceed. A cancellation stops the run quietly (the session is
        already HALTED); any other non-completion is a hard failure.
        """
        if outcome.is_completed:
            return True
        if outcome.status is LoopStatus.CANCELLED:
            logger.info(
                "%s phase cancelled after %d step(s); stopping", phase.value, outcome.steps_used
            )
            return False
        raise DevMindError(
            f"the {phase.value} phase ended as {outcome.status.value} after "
            f"{outcome.steps_used} step(s) without finishing",
            details={"phase": phase.value, "status": outcome.status.value},
        )

    async def _working_tree_diff(self, workbench: SessionWorkbench) -> str:
        result = await workbench.tool_context.sandbox.run(SandboxCommand(argv=("git", "diff")))
        return result.stdout

    # --- helpers -----------------------------------------------------------

    def _system_prefix(self, ingestion: IngestionResult) -> str:
        return self._prompts.render("system_agent") + "\n\n" + ingestion.brief.render()

    @staticmethod
    def _issue_line(session: SessionRead) -> str:
        return session.issue_title or session.issue_body or "(no issue text available)"

    @staticmethod
    def _format_plan(items: list[TodoItemRead]) -> str:
        return "\n".join(f"{index}. {item.content}" for index, item in enumerate(items, start=1))

    def _load(self, session_id: str) -> SessionRead:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            raise SessionNotFoundError(
                f"session {session_id} not found", details={"session_id": session_id}
            )
        return SessionRead.model_validate(model)

    def _fail(self, session_id: str, exc: DevMindError) -> None:
        logger.warning("session %s failed: %s", session_id, exc.message)
        model = self._sessions.get_by_id(session_id)
        if model is not None and model.status.can_transition_to(SessionStatus.FAILED):
            self._state.transition(session_id, SessionStatus.FAILED, reason=exc.message)
        self._events.append(
            session_id,
            EventType.SESSION_FAILED,
            {"error": exc.message, "type": type(exc).__name__},
        )

    async def _safe_cleanup(self, session_id: str, workbench: SessionWorkbench) -> None:
        try:
            await workbench.cleanup()
        except Exception:
            logger.exception("workbench cleanup failed for session %s", session_id)
