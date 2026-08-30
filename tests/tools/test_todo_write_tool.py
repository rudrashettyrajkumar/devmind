from __future__ import annotations

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, TodoStatus
from devmind.repositories import EventRepository, TodoRepository
from devmind.schemas.tools import TodoItemWrite, TodoWriteInput
from devmind.tools.todo_write_tool import TodoWriteTool
from devmind.tools.tool_context import ToolContext


async def test_persists_the_plan_and_emits_plan_updated(
    tool_context: ToolContext, db_session: SQLAlchemySession
) -> None:
    result = await TodoWriteTool().execute(
        TodoWriteInput(
            items=(
                TodoItemWrite(content="read calc.py", status=TodoStatus.DONE),
                TodoItemWrite(content="fix add()", status=TodoStatus.IN_PROGRESS),
                TodoItemWrite(content="run tests"),
            )
        ),
        tool_context,
    )
    assert not result.is_error
    assert result.metadata["count"] == 3

    rows = TodoRepository(db_session).list_for_session(tool_context.session_id)
    assert [r.content for r in rows] == ["read calc.py", "fix add()", "run tests"]
    assert [r.status for r in rows] == [
        TodoStatus.DONE,
        TodoStatus.IN_PROGRESS,
        TodoStatus.PENDING,
    ]

    events = EventRepository(db_session).list_since(tool_context.session_id)
    assert any(e.event_type is EventType.PLAN_UPDATED for e in events)


async def test_second_write_replaces_the_first(
    tool_context: ToolContext, db_session: SQLAlchemySession
) -> None:
    await TodoWriteTool().execute(
        TodoWriteInput(items=(TodoItemWrite(content="old step"),)), tool_context
    )
    await TodoWriteTool().execute(
        TodoWriteInput(
            items=(TodoItemWrite(content="new step a"), TodoItemWrite(content="new step b"))
        ),
        tool_context,
    )
    rows = TodoRepository(db_session).list_for_session(tool_context.session_id)
    assert [r.content for r in rows] == ["new step a", "new step b"]
