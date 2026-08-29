import pytest
from pydantic import ValidationError

from devmind.core.enums import Effort, StopReason
from devmind.schemas.llm import LLMRequest, LLMResponse, TokenUsage, ToolCall


def test_tool_call_arguments_default_to_empty_dict() -> None:
    call = ToolCall(id="toolu_1", name="read_file")
    assert call.arguments == {}


def test_llm_request_requires_system_and_messages() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(messages=[])  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        LLMRequest(system="x")  # type: ignore[call-arg]


def test_llm_request_defaults() -> None:
    request = LLMRequest(system="you are an agent", messages=[{"role": "user"}])
    assert request.effort is Effort.HIGH
    assert request.tools == []
    assert request.max_tokens == 16_000
    assert request.cache_breakpoints == 2
    assert request.enable_context_editing is False


def test_llm_request_coerces_effort_string_to_enum() -> None:
    request = LLMRequest(system="s", messages=[], effort="low")  # type: ignore[arg-type]
    assert request.effort is Effort.LOW


def test_llm_request_rejects_unknown_effort() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(system="s", messages=[], effort="turbo")  # type: ignore[arg-type]


@pytest.mark.parametrize("breakpoints", [-1, 5])
def test_llm_request_cache_breakpoints_bounded(breakpoints: int) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(system="s", messages=[], cache_breakpoints=breakpoints)


def test_token_usage_is_frozen_with_zero_defaults() -> None:
    usage = TokenUsage()
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)
    assert usage.cache_read_input_tokens == 0
    with pytest.raises(ValidationError):
        usage.input_tokens = 5  # type: ignore[misc]


def test_llm_response_requires_raw_content_and_stop_reason() -> None:
    response = LLMResponse(
        text="done",
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(),
        raw_content=[{"type": "text", "text": "done"}],
    )
    assert response.tool_calls == []
    with pytest.raises(ValidationError):
        LLMResponse(text="x", usage=TokenUsage(), raw_content=[])  # type: ignore[call-arg]
