"""`ToolExecutor` — the one place a tool call is turned into a result (E6).

Contract, and every step matters:

1. Look up the tool; unknown name → `is_error` result naming the valid tools.
2. Validate the parsed arguments against `input_model`; a `ValidationError` becomes an
   `is_error` result quoting the message, so the model can correct itself.
3. Emit `TOOL_CALL` with the arguments.
4. `await tool.execute(...)`.
5. Catch **everything**: a `DevMindError` becomes an `is_error` result with its message;
   any other exception becomes a generic `is_error` result with the traceback logged.
   A tool error never propagates out of the executor — a crashed tool must not kill a
   session that could still recover.
6. Truncate to `MAX_TOOL_RESULT_CHARS`.
7. Emit `TOOL_RESULT`.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ValidationError

from devmind.core.enums import EventType
from devmind.exceptions import DevMindError, ToolExecutionError
from devmind.interfaces.tool import Tool
from devmind.repositories.event_repository import EventRepository
from devmind.schemas.llm import ToolCall, ToolResultBlock
from devmind.schemas.tools import ToolResult
from devmind.services.output_truncator import OutputTruncator
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Validates, dispatches, audits, and truncates one tool call."""

    def __init__(
        self, registry: ToolRegistry, events: EventRepository, truncator: OutputTruncator
    ) -> None:
        self._registry = registry
        self._events = events
        self._truncator = truncator

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResultBlock:
        try:
            tool = self._registry.get(call.name)
        except ToolExecutionError as exc:
            return self._finish(ctx, call, ToolResult(content=exc.message, is_error=True))

        try:
            payload = tool.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            return self._finish(
                ctx,
                call,
                ToolResult(content=f"invalid arguments for {call.name!r}: {exc}", is_error=True),
            )

        self._events.append(
            ctx.session_id,
            EventType.TOOL_CALL,
            {"tool": call.name, "call_id": call.id, "arguments": dict(call.arguments)},
        )

        result = await self._run(tool, payload, ctx, call)
        return self._finish(ctx, call, result)

    async def _run(
        self, tool: Tool, payload: BaseModel, ctx: ToolContext, call: ToolCall
    ) -> ToolResult:
        try:
            return await tool.execute(payload, ctx)
        except DevMindError as exc:
            logger.info("tool %s returned a domain error: %s", call.name, exc.message)
            return ToolResult(content=exc.message, is_error=True)
        except Exception:
            logger.exception("tool %s raised an unexpected exception", call.name)
            return ToolResult(
                content=(
                    f"the {call.name!r} tool failed with an internal error; "
                    "the details were logged. Try a different approach."
                ),
                is_error=True,
            )

    def _finish(self, ctx: ToolContext, call: ToolCall, result: ToolResult) -> ToolResultBlock:
        content, truncated = self._truncator.truncate(result.content)
        self._events.append(
            ctx.session_id,
            EventType.TOOL_RESULT,
            {
                "tool": call.name,
                "call_id": call.id,
                "is_error": result.is_error,
                "truncated": truncated,
                "metadata": dict(result.metadata),
            },
        )
        return ToolResultBlock(tool_use_id=call.id, content=content, is_error=result.is_error)
