from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

import pytest
from anthropic import AsyncAnthropic

from devmind.core.config import Settings
from devmind.core.enums import Effort, StopReason
from devmind.exceptions import LLMProviderError
from devmind.schemas.llm import LLMRequest, TokenUsage
from devmind.services.anthropic_provider import AnthropicProvider
from devmind.services.cost_calculator import CostCalculator
from tests.services._fake_anthropic import FakeAsyncAnthropic, build_message

_SRC = Path(__file__).resolve().parents[2] / "src" / "devmind"


@pytest.fixture
def settings() -> Settings:
    return Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]


def _provider(fake: FakeAsyncAnthropic, settings: Settings) -> AnthropicProvider:
    return AnthropicProvider(cast(AsyncAnthropic, fake), settings, CostCalculator())


def _request(**overrides: object) -> LLMRequest:
    base: dict[str, object] = {
        "system": "you are an agent",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 4_000,
    }
    base.update(overrides)
    return LLMRequest(**base)  # type: ignore[arg-type]


async def test_request_shape_has_adaptive_thinking_and_effort_in_output_config(
    settings: Settings,
) -> None:
    fake = FakeAsyncAnthropic()
    await _provider(fake, settings).complete(_request(effort=Effort.LOW))

    sent = fake.messages.create_calls[0]
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "low"}
    assert sent["model"] == "claude-opus-5"


async def test_request_carries_no_removed_sampling_or_budget_params(
    settings: Settings,
) -> None:
    fake = FakeAsyncAnthropic()
    await _provider(fake, settings).complete(_request())

    sent = fake.messages.create_calls[0]
    for forbidden in ("temperature", "top_p", "top_k", "budget_tokens"):
        assert forbidden not in sent
    assert "budget_tokens" not in sent["thinking"]


async def test_small_max_tokens_uses_create_large_uses_stream(settings: Settings) -> None:
    small = FakeAsyncAnthropic()
    await _provider(small, settings).complete(_request(max_tokens=4_000))
    assert small.messages.create_calls and not small.messages.stream_calls

    large = FakeAsyncAnthropic()
    await _provider(large, settings).complete(_request(max_tokens=64_000))
    assert large.messages.stream_calls and not large.messages.create_calls


async def test_response_text_and_tool_calls_are_parsed(settings: Settings) -> None:
    fake = FakeAsyncAnthropic(
        result=build_message(
            content=[
                {"type": "text", "text": "let me look"},
                {
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "read_file",
                    "input": {"path": "src/calc.py"},
                },
            ],
            stop_reason="tool_use",
        )
    )
    response = await _provider(fake, settings).complete(_request())

    assert response.text == "let me look"
    assert response.stop_reason is StopReason.TOOL_USE
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert (call.id, call.name, call.arguments) == (
        "toolu_9",
        "read_file",
        {"path": "src/calc.py"},
    )


async def test_raw_content_is_the_sdk_blocks_verbatim_not_rebuilt_from_text(
    settings: Settings,
) -> None:
    message = build_message(
        content=[
            {"type": "thinking", "thinking": "hmm", "signature": "sig-abc"},
            {"type": "text", "text": "answer"},
        ]
    )
    fake = FakeAsyncAnthropic(result=message)
    response = await _provider(fake, settings).complete(_request())

    # Passed through exactly as the SDK serialized them — thinking block and its
    # signature preserved, so the next turn can echo them back.
    assert response.raw_content == message.model_dump(mode="json")["content"]
    thinking_block = response.raw_content[0]
    assert thinking_block["type"] == "thinking"
    assert thinking_block["signature"] == "sig-abc"
    assert response.text == "answer"


async def test_usage_is_extracted_including_cache_counters(settings: Settings) -> None:
    fake = FakeAsyncAnthropic(
        result=build_message(
            usage={
                "input_tokens": 400,
                "output_tokens": 50,
                "cache_read_input_tokens": 1_200,
                "cache_creation_input_tokens": 30,
            }
        )
    )
    response = await _provider(fake, settings).complete(_request())

    assert response.usage.input_tokens == 400
    assert response.usage.cache_read_input_tokens == 1_200
    assert response.usage.cache_creation_input_tokens == 30


async def test_refusal_stop_reason_is_returned_not_raised(settings: Settings) -> None:
    fake = FakeAsyncAnthropic(
        result=build_message(content=[{"type": "text", "text": ""}], stop_reason="refusal")
    )
    response = await _provider(fake, settings).complete(_request())
    assert response.stop_reason is StopReason.REFUSAL


async def test_string_tool_input_is_json_parsed(settings: Settings) -> None:
    fake = FakeAsyncAnthropic(
        result=build_message(
            content=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "search_code",
                    "input": {"pattern": "def add", "glob": "*.py"},
                }
            ],
            stop_reason="tool_use",
        )
    )
    provider = _provider(fake, settings)
    # The SDK hands back a dict; Opus 5 sometimes serializes it as a JSON string,
    # which the provider must json.loads rather than string-match.
    assert provider._coerce_arguments('{"pattern": "def add"}') == {"pattern": "def add"}
    response = await provider.complete(_request())
    assert response.tool_calls[0].arguments == {"pattern": "def add", "glob": "*.py"}


async def test_context_editing_flag_routes_through_beta_with_the_strategy(
    settings: Settings,
) -> None:
    fake = FakeAsyncAnthropic()
    await _provider(fake, settings).complete(_request(enable_context_editing=True))

    assert not fake.messages.calls
    sent = fake.beta.messages.create_calls[0]
    assert sent["betas"] == ["context-management-2025-06-27"]
    assert sent["context_management"] == {"edits": [{"type": "clear_tool_uses_20250919"}]}


async def test_context_editing_and_streaming_use_the_beta_stream_path(
    settings: Settings,
) -> None:
    fake = FakeAsyncAnthropic()
    await _provider(fake, settings).complete(
        _request(enable_context_editing=True, max_tokens=64_000)
    )
    assert fake.beta.messages.stream_calls and not fake.beta.messages.create_calls
    assert not fake.messages.calls


@pytest.mark.parametrize("raw", ["something_new", 123, None])
def test_unrecognized_stop_reason_falls_back_to_end_turn(settings: Settings, raw: object) -> None:
    assert _provider(FakeAsyncAnthropic(), settings)._stop_reason(raw) is StopReason.END_TURN


def test_known_stop_reason_strings_map_through(settings: Settings) -> None:
    provider = _provider(FakeAsyncAnthropic(), settings)
    assert provider._stop_reason("refusal") is StopReason.REFUSAL
    assert provider._stop_reason("tool_use") is StopReason.TOOL_USE


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_use", "id": "toolu_1", "input": {}},
        {"type": "tool_use", "name": "read_file", "input": {}},
        {"type": "tool_use", "id": 5, "name": "read_file", "input": {}},
    ],
)
def test_malformed_tool_use_block_raises_llm_provider_error(
    settings: Settings, block: dict[str, object]
) -> None:
    provider = _provider(FakeAsyncAnthropic(), settings)
    with pytest.raises(LLMProviderError, match="missing id or name"):
        provider._tool_call(block)


async def test_content_that_is_not_a_list_yields_empty_raw_content(
    settings: Settings,
) -> None:
    provider = _provider(FakeAsyncAnthropic(), settings)
    assert provider._raw_content({"content": "not-a-list"}) == []


def test_coerce_arguments_rejects_non_json_string(settings: Settings) -> None:
    provider = _provider(FakeAsyncAnthropic(), settings)
    with pytest.raises(LLMProviderError, match="not valid JSON"):
        provider._coerce_arguments("{not json")


def test_coerce_arguments_rejects_a_non_object(settings: Settings) -> None:
    provider = _provider(FakeAsyncAnthropic(), settings)
    with pytest.raises(LLMProviderError, match="did not decode to a JSON object"):
        provider._coerce_arguments("[1, 2, 3]")


async def test_sustained_zero_cache_reads_warns_after_the_first_call(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    zero_usage = {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    fake = FakeAsyncAnthropic(result=build_message(usage=zero_usage))
    provider = _provider(fake, settings)

    caplog.set_level("WARNING", logger="devmind.services.anthropic_provider")
    for _ in range(4):
        await provider.complete(_request())

    warnings = [r for r in caplog.records if "cache_read_input_tokens has been zero" in r.message]
    assert warnings, "expected a sustained-zero-cache-read warning"


async def test_a_cache_hit_resets_the_zero_streak(settings: Settings) -> None:
    hit_usage = {
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_input_tokens": 4_000,
        "cache_creation_input_tokens": 0,
    }
    zero_usage = {**hit_usage, "cache_read_input_tokens": 0}
    provider = _provider(FakeAsyncAnthropic(), settings)

    # First call is exempt; calls 2 and 3 build a zero-streak; call 4 is a cache hit.
    for usage in (zero_usage, zero_usage, zero_usage, hit_usage):
        provider._record_call(TokenUsage.model_validate(usage))
    assert provider._zero_cache_read_streak == 0


def _module_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def test_anthropic_is_imported_in_exactly_one_src_module() -> None:
    importers: set[str] = set()
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = _module_names(node)
            if any(name == "anthropic" or name.startswith("anthropic.") for name in names):
                importers.add(str(path.relative_to(_SRC)))

    assert sorted(importers) == ["services/anthropic_provider.py"]
