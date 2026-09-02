"""`AgentLoop` — the hand-written ReAct loop that drives one phase (E7-F1).

A dedicated loop rather than the SDK's `tool_runner`: this needs a persisted event
per step, a step budget, a session cost ceiling, cooperative cancellation, and
phase-swapped context — control the runner does not expose (design §6). Per step, in
order (spec §AgentLoop):

1. Cancellation → `LoopOutcome.cancelled()`.
2. Session cost ceiling → raise `BudgetExceededError` (a session-wide fault).
3. `compactor.compact_if_needed(ctx)`.
4. `llm.complete(ctx.to_request(phase))`.
5. Record usage and cost; emit `LLM_CALL`.
6. `END_TURN` → `LoopOutcome.completed`.
7. Execute tool calls — concurrently when the model batched more than one.
8. A `finish` call → `LoopOutcome.completed` with its summary and confidence.
9. `ctx.extend(response, results)` (this advances the step counter).

Step budget reached → `LoopOutcome.budget_exhausted()`. The caller decides whether
that is fatal; the loop does not set policy.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from devmind.core.enums import AgentPhase, EventType, SessionStatus, StopReason, ToolName
from devmind.exceptions import BudgetExceededError
from devmind.interfaces.llm_provider import LLMProvider
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.agent import FinishSignal, LoopOutcome
from devmind.schemas.llm import LLMResponse, ToolCall, ToolResultBlock
from devmind.schemas.tools import FinishInput
from devmind.services.agent_context import AgentContext
from devmind.services.context_compactor import ContextCompactor
from devmind.services.cost_calculator import CostCalculator
from devmind.services.tool_executor import ToolExecutor
from devmind.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class AgentLoop:
    """Runs one phase to completion, its step budget, a cancellation, or a cost stop."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        executor: ToolExecutor,
        events: EventRepository,
        compactor: ContextCompactor,
        cost: CostCalculator,
        sessions: SessionRepository,
        *,
        model: str,
        cost_ceiling_usd: float,
    ) -> None:
        # `model` and `cost_ceiling_usd` are not in the spec's __init__ sketch but the
        # loop cannot price a call or enforce the ceiling without them; passed
        # explicitly rather than reaching for a `Settings` object mid-layer.
        self._llm = llm_provider
        self._executor = executor
        self._events = events
        self._compactor = compactor
        self._cost = cost
        self._sessions = sessions
        self._model = model
        self._cost_ceiling_usd = cost_ceiling_usd

    async def run(self, ctx: AgentContext, tool_ctx: ToolContext, phase: AgentPhase) -> LoopOutcome:
        session_id = tool_ctx.session_id
        while ctx.steps_used < ctx.step_budget:
            if self._is_cancelled(session_id):
                logger.info("session %s cancelled; halting the %s phase", session_id, phase.value)
                return LoopOutcome.cancelled(steps_used=ctx.steps_used)

            self._check_cost_ceiling(session_id)
            await self._compactor.compact_if_needed(ctx)

            response = await self._llm.complete(ctx.to_request(phase))
            self._record_call(session_id, phase, ctx.steps_used, response)

            if response.stop_reason is StopReason.REFUSAL:
                logger.warning(
                    "model refused during the %s phase of session %s", phase.value, session_id
                )
                return LoopOutcome.failed(steps_used=ctx.steps_used, final_text=response.text)
            if response.stop_reason is StopReason.END_TURN or not response.tool_calls:
                return LoopOutcome.completed(steps_used=ctx.steps_used, final_text=response.text)

            results, finish = await self._execute_tool_calls(
                ctx, tool_ctx, phase, response.tool_calls
            )
            ctx.extend(response, results)

            if finish is not None:
                return LoopOutcome.completed(steps_used=ctx.steps_used, finish=finish)

        return LoopOutcome.budget_exhausted(steps_used=ctx.steps_used)

    # --- per-step guards --------------------------------------------------------

    def _is_cancelled(self, session_id: str) -> bool:
        model = self._sessions.get_by_id(session_id)
        return model is None or model.status is SessionStatus.HALTED

    def _check_cost_ceiling(self, session_id: str) -> None:
        model = self._sessions.get_by_id(session_id)
        if model is None:
            return
        if model.estimated_cost_usd >= self._cost_ceiling_usd:
            raise BudgetExceededError(
                f"session {session_id} reached its cost ceiling "
                f"(${model.estimated_cost_usd:.4f} >= ${self._cost_ceiling_usd:.2f})",
                details={
                    "session_id": session_id,
                    "cost_usd": model.estimated_cost_usd,
                    "ceiling_usd": self._cost_ceiling_usd,
                },
            )

    # --- accounting -------------------------------------------------------------

    def _record_call(
        self, session_id: str, phase: AgentPhase, step: int, response: LLMResponse
    ) -> None:
        usage = response.usage
        cost = self._cost.cost_for(self._model, usage)
        self._sessions.record_usage(
            session_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cost_usd=cost,
        )
        self._events.append(
            session_id,
            EventType.LLM_CALL,
            {
                "phase": phase.value,
                "step": step,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cost_usd": cost,
                "stop_reason": response.stop_reason.value,
            },
        )

    # --- tool dispatch --------------------------------------------------------

    async def _execute_tool_calls(
        self,
        ctx: AgentContext,
        tool_ctx: ToolContext,
        phase: AgentPhase,
        calls: list[ToolCall],
    ) -> tuple[list[ToolResultBlock], FinishSignal | None]:
        if len(calls) == 1:
            blocks = [await self._dispatch_one(ctx, tool_ctx, phase, calls[0])]
        else:
            # The model batched these deliberately; run them together so throughput
            # does not collapse to one tool per turn.
            blocks = list(
                await asyncio.gather(
                    *(self._dispatch_one(ctx, tool_ctx, phase, call) for call in calls)
                )
            )
        return blocks, self._finish_signal(calls, blocks)

    async def _dispatch_one(
        self, ctx: AgentContext, tool_ctx: ToolContext, phase: AgentPhase, call: ToolCall
    ) -> ToolResultBlock:
        if call.name not in ctx.allowed_tool_names:
            available = ", ".join(sorted(ctx.allowed_tool_names))
            return ToolResultBlock(
                tool_use_id=call.id,
                content=(
                    f"the {call.name!r} tool is not available in the {phase.value} "
                    f"phase. Available tools: {available}"
                ),
                is_error=True,
            )
        return await self._executor.execute(call, tool_ctx)

    @staticmethod
    def _finish_signal(calls: list[ToolCall], blocks: list[ToolResultBlock]) -> FinishSignal | None:
        by_id = {block.tool_use_id: block for block in blocks}
        for call in calls:
            if call.name != ToolName.FINISH.value:
                continue
            block = by_id.get(call.id)
            if block is None or block.is_error:
                continue
            try:
                parsed = FinishInput.model_validate(call.arguments)
            except ValidationError:
                continue
            return FinishSignal(summary=parsed.summary, confidence=parsed.confidence)
        return None
