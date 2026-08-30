from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, ToolName
from devmind.exceptions import SandboxError
from devmind.interfaces.tool import Tool
from devmind.repositories import EventRepository
from devmind.schemas.llm import ToolCall
from devmind.schemas.tools import ListDirInput, ToolResult, WriteFileInput
from devmind.services.output_truncator import OutputTruncator
from devmind.services.tool_executor import ToolExecutor
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_context import ToolContext


class _EchoTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.LIST_DIR

    @property
    def description(self) -> str:
        return "echo"

    @property
    def input_model(self) -> type[BaseModel]:
        return ListDirInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, ListDirInput)
        return ToolResult(content=f"listed {payload.path} x" * 5000)


class _RaisingTool(_EchoTool):
    @property
    def name(self) -> ToolName:
        return ToolName.READ_FILE

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("boom")


class _DomainErrorTool(_EchoTool):
    @property
    def name(self) -> ToolName:
        return ToolName.WRITE_FILE

    @property
    def input_model(self) -> type[BaseModel]:
        return WriteFileInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        raise SandboxError("binary not allowed")


@pytest.fixture
def executor(db_session: SQLAlchemySession) -> ToolExecutor:
    reg = ToolRegistry()
    reg.register_all([_EchoTool(), _RaisingTool(), _DomainErrorTool()])
    return ToolExecutor(reg, EventRepository(db_session), OutputTruncator(200))


async def _run(executor: ToolExecutor, ctx: ToolContext, name: str, **args: object) -> object:
    return await executor.execute(ToolCall(id="c1", name=name, arguments=args), ctx)


async def test_unknown_tool_becomes_error_result(
    executor: ToolExecutor, tool_context: ToolContext
) -> None:
    block = await _run(executor, tool_context, "nope")
    assert block.is_error
    assert "unknown tool" in block.content


async def test_invalid_arguments_become_error_result(
    executor: ToolExecutor, tool_context: ToolContext
) -> None:
    block = await _run(executor, tool_context, "list_dir", depth=99)  # depth > max
    assert block.is_error
    assert "invalid arguments" in block.content


async def test_raising_tool_becomes_error_result_not_an_exception(
    executor: ToolExecutor, tool_context: ToolContext
) -> None:
    block = await _run(executor, tool_context, "read_file", path="x")
    assert block.is_error
    assert "internal error" in block.content


async def test_domain_error_message_is_surfaced(
    executor: ToolExecutor, tool_context: ToolContext
) -> None:
    block = await _run(executor, tool_context, "write_file", path="x", content="y")
    assert block.is_error
    assert block.content == "binary not allowed"


async def test_result_is_truncated_and_events_are_emitted(
    executor: ToolExecutor, tool_context: ToolContext, db_session: SQLAlchemySession
) -> None:
    block = await _run(executor, tool_context, "list_dir", path="src")
    assert len(block.content) < 400
    assert "truncated" in block.content

    events = EventRepository(db_session).list_since(tool_context.session_id)
    kinds = [e.event_type for e in events]
    assert EventType.TOOL_CALL in kinds
    assert EventType.TOOL_RESULT in kinds


async def test_tool_use_id_is_echoed_back(
    executor: ToolExecutor, tool_context: ToolContext
) -> None:
    block = await executor.execute(
        ToolCall(id="abc-123", name="list_dir", arguments={"path": "src"}), tool_context
    )
    assert block.tool_use_id == "abc-123"
