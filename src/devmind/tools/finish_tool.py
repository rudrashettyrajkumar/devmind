"""`finish` — a deliberate, structured exit from the current phase.

The agent loop (E7) watches for this tool call to end a phase cleanly rather than
running to its step budget. E6 ships the tool; it records the summary and confidence
and returns them — the loop reads the result.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import FinishInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "End the current phase. Provide a `summary` of what you accomplished and a "
    "`confidence` from 0 to 1 that the phase goal was met. Call this only when there "
    "is nothing useful left to do in this phase."
)


class FinishTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.FINISH

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return FinishInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, FinishInput)
        return ToolResult(
            content=f"phase finished (confidence {payload.confidence:.2f}): {payload.summary}",
            metadata={"summary": payload.summary, "confidence": payload.confidence},
        )
