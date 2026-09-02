"""`AgentContext` — transcript shape, token estimate, and the phase tool gate (E7-F1-T1)."""

from __future__ import annotations

from devmind.core.enums import AgentPhase, StopReason
from devmind.schemas.llm import LLMResponse, TokenUsage, ToolCall, ToolResultBlock
from devmind.services.agent_context import AgentContext


def _tool_use_response(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_USE,
        usage=TokenUsage(),
        raw_content=[
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls
        ],
    )


def _ctx(step_budget: int = 5) -> AgentContext:
    return AgentContext(
        session_id="s1",
        system="SYS",
        tools=[{"name": "read_file", "description": "d", "input_schema": {}}],
        step_budget=step_budget,
    )


def test_allowed_tool_names_come_from_the_schemas() -> None:
    ctx = _ctx()
    assert ctx.allowed_tool_names == frozenset({"read_file"})


def test_seeded_message_and_to_request() -> None:
    ctx = _ctx()
    ctx.add_user_message("investigate the bug")
    request = ctx.to_request(AgentPhase.INVESTIGATION)

    assert request.system == "SYS"
    assert request.tools[0]["name"] == "read_file"
    assert request.messages[0]["role"] == "user"
    assert request.enable_context_editing is False


def test_extend_appends_assistant_verbatim_then_one_user_message() -> None:
    ctx = _ctx()
    ctx.add_user_message("go")
    response = _tool_use_response(
        ToolCall(id="a", name="read_file", arguments={"path": "x.py"}),
        ToolCall(id="b", name="read_file", arguments={"path": "y.py"}),
    )
    results = [
        ToolResultBlock(tool_use_id="a", content="x body"),
        ToolResultBlock(tool_use_id="b", content="y body", is_error=True),
    ]

    ctx.extend(response, results)
    messages = ctx.messages

    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == response.raw_content  # verbatim, not rebuilt
    assert messages[2]["role"] == "user"
    blocks = messages[2]["content"]
    assert isinstance(blocks, list) and len(blocks) == 2
    assert {b["type"] for b in blocks} == {"tool_result"}
    assert ctx.steps_used == 1
    assert ctx.remaining_steps == 4


def test_enable_context_editing_flows_into_the_request() -> None:
    ctx = _ctx()
    ctx.enable_context_editing()
    assert ctx.to_request(AgentPhase.EDITING).enable_context_editing is True


def test_estimated_tokens_grows_with_the_transcript() -> None:
    ctx = _ctx()
    before = ctx.estimated_tokens
    ctx.add_user_message("x" * 4_000)
    assert ctx.estimated_tokens >= before + 900


def test_git_diff_result_is_captured_as_the_running_diff() -> None:
    ctx = _ctx()
    response = _tool_use_response(ToolCall(id="d1", name="git_diff", arguments={}))
    ctx.extend(response, [ToolResultBlock(tool_use_id="d1", content="diff --git a/x b/x")])
    assert ctx.diff_text == "diff --git a/x b/x"


def test_reanchor_restates_plan_and_diff_as_a_user_message() -> None:
    ctx = _ctx()
    ctx.reanchor("1. do a thing", "diff --git a/x b/x")
    last = ctx.messages[-1]
    text = last["content"][0]["text"]
    assert last["role"] == "user"
    assert "1. do a thing" in text
    assert "diff --git a/x b/x" in text


def test_drop_superseded_reads_blanks_reads_of_later_edited_files() -> None:
    ctx = _ctx()
    ctx.extend(
        _tool_use_response(ToolCall(id="r1", name="read_file", arguments={"path": "a.py"})),
        [ToolResultBlock(tool_use_id="r1", content="ORIGINAL SOURCE OF a.py")],
    )
    ctx.extend(
        _tool_use_response(
            ToolCall(id="w1", name="write_file", arguments={"path": "a.py", "content": "new"})
        ),
        [ToolResultBlock(tool_use_id="w1", content="wrote a.py")],
    )

    dropped = ctx.drop_superseded_reads()

    assert dropped == 1
    bodies = [
        block["content"]
        for message in ctx.messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert "ORIGINAL SOURCE OF a.py" not in bodies
    assert any("stale read of a.py" in body for body in bodies)
    assert ctx.drop_superseded_reads() == 0  # idempotent — already blanked
