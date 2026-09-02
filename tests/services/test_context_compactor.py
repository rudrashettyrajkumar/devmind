"""`ContextCompactor` — fires at the threshold, enables server-side clearing, drops
stale reads, and re-anchors the plan and diff (E7-F1-T4)."""

from __future__ import annotations

from devmind.core.enums import StopReason
from devmind.schemas.llm import LLMResponse, TokenUsage, ToolCall, ToolResultBlock
from devmind.services.agent_context import AgentContext
from devmind.services.context_compactor import ContextCompactor


def _ctx(system: str = "SYS") -> AgentContext:
    return AgentContext(
        session_id="s1",
        system=system,
        tools=[{"name": "read_file"}, {"name": "write_file"}, {"name": "finish"}],
        step_budget=20,
    )


def _tool_use(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_USE,
        usage=TokenUsage(),
        raw_content=[
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls
        ],
    )


async def test_below_threshold_is_a_no_op() -> None:
    compactor = ContextCompactor(max_context_tokens=100_000, threshold=0.7)
    ctx = _ctx()
    ctx.add_user_message("small")

    assert await compactor.compact_if_needed(ctx) is False
    assert ctx.context_editing_enabled is False


async def test_compaction_enables_editing_and_reanchors_plan_and_diff() -> None:
    compactor = ContextCompactor(max_context_tokens=100, threshold=0.5)  # trips at ~200 chars
    ctx = _ctx(system="x" * 1_200)
    ctx.add_user_message("noise " * 100)
    ctx.plan_text = "1. inspect calc.py\n2. flip the operator"
    ctx.diff_text = "diff --git a/calc.py b/calc.py\n-a - b\n+a + b"

    did = await compactor.compact_if_needed(ctx)

    assert did is True
    assert ctx.context_editing_enabled is True
    last = ctx.messages[-1]
    text = last["content"][0]["text"]
    assert "flip the operator" in text
    assert "a + b" in text


async def test_compaction_blanks_reads_of_files_later_edited() -> None:
    compactor = ContextCompactor(max_context_tokens=100, threshold=0.5)
    ctx = _ctx(system="x" * 1_200)
    ctx.extend(
        _tool_use(ToolCall(id="r1", name="read_file", arguments={"path": "calc.py"})),
        [ToolResultBlock(tool_use_id="r1", content="SECRET ORIGINAL BODY OF calc.py")],
    )
    ctx.extend(
        _tool_use(
            ToolCall(id="w1", name="write_file", arguments={"path": "calc.py", "content": "z"})
        ),
        [ToolResultBlock(tool_use_id="w1", content="wrote calc.py")],
    )

    await compactor.compact_if_needed(ctx)

    bodies = [
        block["content"]
        for message in ctx.messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert "SECRET ORIGINAL BODY OF calc.py" not in bodies
    assert any("stale read of calc.py" in body for body in bodies)
