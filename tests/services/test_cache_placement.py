from __future__ import annotations

import json
from typing import cast

import pytest
from anthropic import AsyncAnthropic

from devmind.core.config import Settings
from devmind.schemas.llm import LLMRequest
from devmind.services.anthropic_provider import AnthropicProvider
from devmind.services.cost_calculator import CostCalculator
from tests.services._fake_anthropic import FakeAsyncAnthropic

_VOLATILE = ["2026-08-28T12:00:00Z", "step 7", "session_id=abc-123", "uuid"]


@pytest.fixture
def settings() -> Settings:
    return Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]


def _provider(fake: FakeAsyncAnthropic, settings: Settings) -> AnthropicProvider:
    return AnthropicProvider(cast(AsyncAnthropic, fake), settings, CostCalculator())


async def _send(request: LLMRequest, settings: Settings) -> dict[str, object]:
    fake = FakeAsyncAnthropic()
    await _provider(fake, settings).complete(request)
    return fake.messages.calls[0]


async def test_cache_control_lands_on_the_last_system_block(settings: Settings) -> None:
    sent = await _send(
        LLMRequest(system="identity and rules", messages=[{"role": "user"}], max_tokens=1_000),
        settings,
    )
    system_blocks = sent["system"]
    assert isinstance(system_blocks, list)
    assert system_blocks[-1]["cache_control"] == {"type": "ephemeral"}


async def test_second_breakpoint_lands_on_the_last_tool(settings: Settings) -> None:
    request = LLMRequest(
        system="rules",
        messages=[{"role": "user"}],
        tools=[{"name": "read_file"}, {"name": "list_dir"}],
        cache_breakpoints=2,
        max_tokens=1_000,
    )
    sent = await _send(request, settings)
    tools = sent["tools"]
    assert isinstance(tools, list)
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}


async def test_one_breakpoint_leaves_tools_uncached(settings: Settings) -> None:
    request = LLMRequest(
        system="rules",
        messages=[{"role": "user"}],
        tools=[{"name": "read_file"}],
        cache_breakpoints=1,
        max_tokens=1_000,
    )
    sent = await _send(request, settings)
    tools = sent["tools"]
    assert isinstance(tools, list)
    assert "cache_control" not in tools[0]


async def test_zero_breakpoints_places_no_cache_control(settings: Settings) -> None:
    request = LLMRequest(
        system="rules",
        messages=[{"role": "user"}],
        tools=[{"name": "read_file"}],
        cache_breakpoints=0,
        max_tokens=1_000,
    )
    sent = await _send(request, settings)
    assert isinstance(sent["system"], list)
    assert "cache_control" not in sent["system"][-1]
    assert isinstance(sent["tools"], list)
    assert "cache_control" not in sent["tools"][0]


async def test_no_volatile_value_appears_in_any_system_block(settings: Settings) -> None:
    # The provider must never inject a timestamp/step/uuid — the system prefix is
    # exactly what the caller passed, nothing more.
    request = LLMRequest(
        system="identity and standing rules only",
        messages=[{"role": "user", "content": "current step 7 at 2026-08-28"}],
        max_tokens=1_000,
    )
    sent = await _send(request, settings)
    rendered = json.dumps(sent["system"])
    for token in _VOLATILE:
        assert token not in rendered


async def test_tool_blocks_are_copied_not_mutated_on_the_request(settings: Settings) -> None:
    original_tool = {"name": "read_file"}
    request = LLMRequest(
        system="rules",
        messages=[{"role": "user"}],
        tools=[original_tool],
        cache_breakpoints=2,
        max_tokens=1_000,
    )
    await _send(request, settings)
    assert original_tool == {"name": "read_file"}
    assert request.tools[0] == {"name": "read_file"}
