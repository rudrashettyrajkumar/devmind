"""`SessionOrchestrator` — drives the state machine from CREATED to SUMMARIZING.

Every status change goes through `SessionStateMachine.transition()`, never a direct
write, so the legal-transition map stays the single source of truth (design §9).

```
CREATED  → INGESTING      RepoIngestionService.ingest()
         → PLANNING        PlannerService.create_plan()
         → INVESTIGATING   baseline test run, then AgentLoop.run(INVESTIGATION)
         → EDITING         AgentLoop.run(EDITING, write tools)
         → TESTING         TestExecutionService + SelfCorrectionController
              │ SUCCEEDED  → SUMMARIZING   (handed to E9)
              │ RETRY      → EDITING        (fix_attempts += 1, FIX_ATTEMPT event)
              │ EXHAUSTED  → EXHAUSTED      (terminal — no verified fix, no PR)
```

Phase-boundary invariants this class enforces:

* **Baseline discipline.** The full suite runs on the clean checkout *before* the
  editing phase. Whatever is already red there is excluded from the verdict — the
  agent is not blamed for a broken `main`, nor credited for fixing it.
* **Investigation** runs with a read-only tool subset and must end with a findings
  summary; that summary — not the transcript — is what crosses into editing.
* **Editing** must produce a non-empty `git diff` on the first pass. An empty diff is
  the "agent believes it fixed something without touching a file" failure.
* **A full suite run precedes SUMMARIZING** — green on three targeted tests is not green.

Any `DevMindError` ends the session `FAILED` with a `failure_reason` and a
`SESSION_FAILED` event. Cleanup runs in `finally`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from devmind.core.enums import (
    TOOLS_BY_PHASE,
    AgentPhase,
    CorrectionAction,
    EventType,
    LoopStatus,
    SessionStatus,
)
from devmind.exceptions import DevMindError, SessionNotFoundError
from devmind.interfaces.sandbox import Sandbox
from devmind.interfaces.workbench_builder import WorkbenchBuilder
from devmind.prompts.loader import PromptLoader
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.agent import LoopOutcome
from devmind.schemas.repo import IngestionResult, RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.session import SessionRead
from devmind.schemas.todo import TodoItemRead
from devmind.services.agent_context import AgentContext
from devmind.services.agent_loop import AgentLoop
from devmind.services.planner_service import PlannerService
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.self_correction_controller import SelfCorrectionController
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.session_workbench import SessionWorkbench
from devmind.services.test_execution_service import TestExecutionService

logger = logging.getLogger(__name__)

# The sandbox does not exist until a workbench is built mid-run, so `TestExecutionService`
# (which takes it in `__init__`, per its spec) is constructed through this factory
# rather than injected whole.
TestExecutionFactory = Callable[[Sandbox], TestExecutionService]


class SessionOrchestrator:
    """Runs one session through ingestion, planning, investigation, editing, and the
    test / self-correction loop.
    """

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
        test_execution_factory: TestExecutionFactory,
        correction: SelfCorrectionController,
        *,
        step_budget: int,
        max_fix_attempts: int,
    ) -> None:
        self._sessions = sessions
        self._state = state_machine
        self._ingestion = ingestion
        self._planner = planner
        self._loop = loop
        self._workbench_builder = workbench_builder
        self._events = events
        self._prompts = prompts
        self._make_test_execution = test_execution_factory
        self._correction = correction
        self._step_budget = step_budget
        self._max_fix_attempts = max_fix_attempts

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

            await self._run_baseline(session_id, ingestion.profile, workbench.sandbox)

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
            await self._run_testing_phase(
                session_id, session, workbench, ingestion.profile, system, plan_text=plan_text
            )
        except DevMindError as exc:
            self._fail(session_id, exc)
        finally:
            if workbench is not None:
                await self._safe_cleanup(session_id, workbench)

    # --- baseline -----------------------------------------------------------

    async def _run_baseline(self, session_id: str, profile: RepoProfile, sandbox: Sandbox) -> None:
        """Full suite on the clean checkout, before any edit (design §8)."""
        result = await self._make_test_execution(sandbox).run_baseline(session_id, profile)
        if result.skipped:
            logger.info(
                "session %s: no test suite — baseline skipped, session is UNVERIFIED", session_id
            )
            return
        report = result.raw_report
        if report is not None and report.collection_error is not None:
            logger.warning(
                "session %s: the suite does not even collect on the clean checkout (%s)",
                session_id,
                report.collection_error,
            )
        elif report is not None and not report.succeeded:
            logger.info(
                "session %s: %d test(s) already red on the clean checkout; excluded from verdict",
                session_id,
                report.failed + report.errors,
            )

    # --- testing / self-correction loop -----------------------------------

    async def _run_testing_phase(
        self,
        session_id: str,
        session: SessionRead,
        workbench: SessionWorkbench,
        profile: RepoProfile,
        system: str,
        *,
        plan_text: str,
    ) -> None:
        if not profile.has_test_suite:
            await self._make_test_execution(workbench.sandbox).run(session_id, profile, attempt=1)
            logger.info(
                "session %s: UNVERIFIED (no test suite) — proceeding to SUMMARIZING", session_id
            )
            self._state.transition(session_id, SessionStatus.SUMMARIZING)
            return

        svc = self._make_test_execution(workbench.sandbox)
        targets: list[str] = []

        for attempt in range(1, self._max_fix_attempts + 1):
            result = await svc.run(session_id, profile, attempt=attempt, node_ids=targets or None)
            if result.verified_green and targets:
                # A narrowed run is not a verdict — confirm with the full suite
                # before the gate (design §8).
                result = await svc.run(session_id, profile, attempt=attempt)

            report = result.report
            assert report is not None  # a non-skipped run always carries a report
            decision = self._correction.decide(session_id, report, attempt)

            if decision.action is CorrectionAction.SUCCEEDED:
                logger.info(
                    "session %s: suite green on attempt %d — SUMMARIZING", session_id, attempt
                )
                self._state.transition(session_id, SessionStatus.SUMMARIZING)
                return

            self._correction.record_attempt(
                session_id,
                attempt=attempt,
                signature=report.signature,
                decision=decision,
            )

            if decision.action is CorrectionAction.EXHAUSTED:
                logger.info(
                    "session %s: self-correction exhausted on attempt %d (%s)",
                    session_id,
                    attempt,
                    decision.reason,
                )
                self._state.transition(session_id, SessionStatus.EXHAUSTED, reason=decision.reason)
                return

            # RETRY: back through EDITING with the failure report as context.
            self._state.transition(session_id, SessionStatus.EDITING)
            self._sessions.increment_fix_attempts(session_id)
            retry = await self._run_phase(
                AgentPhase.EDITING,
                session,
                workbench,
                system,
                plan_text=plan_text,
                instruction=self._prompts.render(
                    "test_failure_analysis",
                    failure_report=report.render(),
                    current_diff=await self._working_tree_diff(workbench),
                    todo_plan=plan_text,
                    attempt_number=attempt + 1,
                    max_attempts=self._max_fix_attempts,
                ),
            )
            if not self._phase_ok(AgentPhase.EDITING, retry):
                return
            if not (await self._working_tree_diff(workbench)).strip():
                logger.warning(
                    "session %s: retry attempt %d changed nothing; the next run will show it",
                    session_id,
                    attempt,
                )
            targets = [f.node_id for f in report.failures]
            self._state.transition(session_id, SessionStatus.TESTING)

        # Unreachable: the controller returns EXHAUSTED once `attempt == max_fix_attempts`.
        raise DevMindError(
            f"session {session_id} left the self-correction loop without a verdict",
            details={"session_id": session_id, "attempts": self._max_fix_attempts},
        )

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
