"""`PlannerService` — issue + repo brief → a concrete, ordered todo plan (E7-F2).

Renders `planner.md`, calls the model with just `todo_write` and `finish` available,
reads the plan out of the `todo_write` call, and checks it: 2-12 items, each
non-empty and phrased as an instruction. A plan of one vague step ("fix the bug") is
a planning failure, not a plan - reject, retry once with an explicit decompose
instruction, then raise `PlanningError` rather than proceed on a plan that carries no
information.

Plans are persisted through `TodoRepository` and versioned in the event log: every
write emits `PLAN_UPDATED` with a monotonic `version`, so the plan's history is
replayable alongside the rest of the session (there is no separate version column —
see the epic report's deviations).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from devmind.core.constants import (
    PLANNER_MAX_ITEMS,
    PLANNER_MIN_ITEMS,
    PLANNER_MIN_WORDS_PER_ITEM,
)
from devmind.core.enums import EventType, ToolName
from devmind.exceptions import PlanningError
from devmind.interfaces.llm_provider import LLMProvider
from devmind.prompts.loader import PromptLoader
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.llm import LLMRequest, LLMResponse
from devmind.schemas.repo import RepoBrief
from devmind.schemas.session import SessionRead
from devmind.schemas.todo import TodoItemRead
from devmind.schemas.tools import TodoWriteInput
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.finish_tool import FinishTool
from devmind.tools.todo_write_tool import TodoWriteTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PlanDraft:
    """The outcome of one planner call: the extracted steps, or why they were rejected."""

    items: tuple[str, ...] = ()
    rejection: str | None = None

    @property
    def ok(self) -> bool:
        return self.rejection is None


class PlannerService:
    """Produces the plan the rest of the session follows."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        prompts: PromptLoader,
        todos: TodoRepository,
        events: EventRepository,
    ) -> None:
        self._llm = llm_provider
        self._prompts = prompts
        self._todos = todos
        self._events = events
        # Only two tools are in play during planning; build their schemas once,
        # byte-stable, through the same builder the agent loop uses.
        planner_registry = ToolRegistry()
        planner_registry.register_all([TodoWriteTool(), FinishTool()])
        self._tool_schemas = planner_registry.to_api_schemas()

    async def create_plan(self, session: SessionRead, brief: RepoBrief) -> list[TodoItemRead]:
        base_prompt = self._prompts.render(
            "planner",
            issue_title=session.issue_title or "(no title — see the description)",
            issue_body=session.issue_body or "(no description provided)",
            repo_brief=brief.render(),
            max_plan_items=PLANNER_MAX_ITEMS,
        )

        draft = self._read_plan(await self._call(base_prompt))
        if not draft.ok:
            logger.info(
                "planner rejected the first plan for session %s: %s",
                session.id,
                draft.rejection,
            )
            retry_prompt = (
                base_prompt
                + "\n\n"
                + self._prompts.render(
                    "planner_retry",
                    reason=draft.rejection,
                    minimum=PLANNER_MIN_ITEMS,
                    maximum=PLANNER_MAX_ITEMS,
                )
            )
            draft = self._read_plan(await self._call(retry_prompt))

        if not draft.ok:
            raise PlanningError(
                f"planner could not produce a usable plan for session {session.id}: "
                f"{draft.rejection}",
                details={"session_id": session.id, "reason": draft.rejection},
            )

        return self._persist(session.id, draft.items)

    # --- model call ------------------------------------------------------------

    async def _call(self, user_prompt: str) -> LLMResponse:
        request = LLMRequest(
            system=self._prompts.render("system_agent"),
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
            tools=self._tool_schemas,
        )
        return await self._llm.complete(request)

    # --- plan extraction and validation --------------------------------------

    def _read_plan(self, response: LLMResponse) -> _PlanDraft:
        for call in response.tool_calls:
            if call.name != ToolName.TODO_WRITE.value:
                continue
            try:
                parsed = TodoWriteInput.model_validate(call.arguments)
            except ValidationError as exc:
                return _PlanDraft(rejection=f"the todo_write arguments were invalid: {exc}")
            items = tuple(item.content.strip() for item in parsed.items)
            rejection = self._reject_reason(items)
            return _PlanDraft(items=items, rejection=rejection)
        return _PlanDraft(rejection="the planner did not call todo_write with a plan")

    @staticmethod
    def _reject_reason(items: tuple[str, ...]) -> str | None:
        if not PLANNER_MIN_ITEMS <= len(items) <= PLANNER_MAX_ITEMS:
            return (
                f"a plan must have between {PLANNER_MIN_ITEMS} and {PLANNER_MAX_ITEMS} "
                f"steps; this one had {len(items)}"
            )
        if any(not item for item in items):
            return "every step must be a non-empty instruction"
        vague = [item for item in items if len(item.split()) < PLANNER_MIN_WORDS_PER_ITEM]
        if vague:
            return (
                "each step must read as an actionable instruction naming what it "
                f"touches, not a label; too terse: {vague[0]!r}"
            )
        return None

    # --- persistence --------------------------------------------------------

    def _persist(self, session_id: str, items: tuple[str, ...]) -> list[TodoItemRead]:
        models = self._todos.replace_all(session_id, items)
        version = self._next_plan_version(session_id)
        self._events.append(
            session_id,
            EventType.PLAN_UPDATED,
            {"version": version, "item_count": len(items), "items": list(items)},
        )
        logger.info(
            "plan v%d persisted for session %s: %d step(s)", version, session_id, len(items)
        )
        return [TodoItemRead.model_validate(model) for model in models]

    def _next_plan_version(self, session_id: str) -> int:
        prior = sum(
            1
            for event in self._events.list_since(session_id, 0, limit=1000)
            if event.event_type is EventType.PLAN_UPDATED
        )
        return prior + 1
