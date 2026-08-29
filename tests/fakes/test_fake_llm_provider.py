from __future__ import annotations

import pytest

from devmind.core.enums import StopReason
from devmind.schemas.llm import LLMRequest, TokenUsage
from tests.fakes.fake_llm_provider import (
    FakeLLMProvider,
    final_text,
    refusal,
    tool_call,
    tool_calls,
)


def _request(system: str = "sys") -> LLMRequest:
    return LLMRequest(system=system, messages=[{"role": "user", "content": "go"}])


async def test_returns_scripted_responses_in_order() -> None:
    provider = FakeLLMProvider([final_text("first"), final_text("second")])
    assert (await provider.complete(_request())).text == "first"
    assert (await provider.complete(_request())).text == "second"


async def test_records_every_request() -> None:
    provider = FakeLLMProvider([final_text("a"), final_text("b")])
    await provider.complete(_request("one"))
    await provider.complete(_request("two"))
    assert [r.system for r in provider.requests] == ["one", "two"]
    assert provider.call_count == 2
    assert provider.last_request().system == "two"


async def test_raises_assertion_error_when_script_is_exhausted() -> None:
    provider = FakeLLMProvider([final_text("only one")])
    await provider.complete(_request())
    with pytest.raises(AssertionError, match="ran out of scripted responses"):
        await provider.complete(_request())


async def test_drives_a_scripted_multi_tool_exchange_end_to_end() -> None:
    provider = FakeLLMProvider(
        [
            tool_call("todo_write", items=["investigate", "patch", "test"]),
            tool_call("read_file", path="src/calc.py"),
            tool_call("apply_patch", path="src/calc.py", old="a - b", new="a + b"),
            tool_call("run_tests"),
            final_text("Fixed the sign error in add()."),
        ]
    )

    names: list[str] = []
    for _ in range(4):
        reply = await provider.complete(_request())
        assert reply.stop_reason is StopReason.TOOL_USE
        assert len(reply.tool_calls) == 1
        names.append(reply.tool_calls[0].name)

    final = await provider.complete(_request())
    assert final.stop_reason is StopReason.END_TURN
    assert final.tool_calls == []
    assert names == ["todo_write", "read_file", "apply_patch", "run_tests"]
    assert provider.call_count == 5


async def test_tool_call_builder_populates_raw_content_for_echo_back() -> None:
    response = tool_call("read_file", call_id="toolu_x", path="a.py")
    assert response.raw_content == [
        {"type": "tool_use", "id": "toolu_x", "name": "read_file", "input": {"path": "a.py"}}
    ]


async def test_tool_calls_builder_batches_into_one_turn() -> None:
    batch = tool_calls(
        tool_call("read_file", path="a.py").tool_calls[0],
        tool_call("read_file", path="b.py").tool_calls[0],
    )
    assert len(batch.tool_calls) == 2
    assert len(batch.raw_content) == 2
    assert batch.stop_reason is StopReason.TOOL_USE


async def test_builders_accept_usage_and_refusal() -> None:
    resp = final_text("done", usage=TokenUsage(input_tokens=10, output_tokens=3))
    assert resp.usage.input_tokens == 10
    assert refusal().stop_reason is StopReason.REFUSAL
