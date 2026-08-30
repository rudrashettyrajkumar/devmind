"""`todo_write` — replace the plan, persist it, and emit `PLAN_UPDATED`.

The plan is always written whole, never patched item by item (see
`TodoRepository.replace_all`). The agent re-sends the full list each time, with each
item's current status, and this tool reconciles the persisted rows to match.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.enums import EventType, TodoStatus, ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import TodoWriteInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Record or update the plan. Send the complete list of steps every time, each "
    "with its `status` (pending / in_progress / done / skipped). Replaces the "
    "previous plan. Keep exactly one step in_progress."
)


class TodoWriteTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.TODO_WRITE

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return TodoWriteInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, TodoWriteInput)
        rows = ctx.todos.replace_all(ctx.session_id, [item.content for item in payload.items])
        for row, item in zip(rows, payload.items, strict=True):
            if item.status is not TodoStatus.PENDING:
                ctx.todos.update_status(row.id, item.status)

        ctx.events.append(
            ctx.session_id,
            EventType.PLAN_UPDATED,
            {
                "items": [
                    {"content": item.content, "status": item.status.value} for item in payload.items
                ]
            },
        )
        return ToolResult(
            content=f"plan saved with {len(payload.items)} step(s)",
            metadata={"count": len(payload.items)},
        )
