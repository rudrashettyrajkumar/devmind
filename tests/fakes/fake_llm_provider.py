"""A deterministic `LLMProvider` for tests, plus builders for readable scripts.

`FakeLLMProvider` returns pre-built `LLMResponse`s in order and records every
`LLMRequest` it was given — the request is as much the thing under test as the
response (prompt assembly, cache breakpoints, context compaction). When the script
runs dry it raises `AssertionError`, so an over-short script surfaces as a clear
failure instead of a mystery hang in an agent-loop test.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from uuid import uuid4

from devmind.core.enums import StopReason
from devmind.interfaces.llm_provider import LLMProvider
from devmind.schemas.llm import LLMRequest, LLMResponse, TokenUsage, ToolCall


class FakeLLMProvider(LLMProvider):
    """Scripted responses in order; every request recorded."""

    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses: deque[LLMResponse] = deque(responses)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(
                f"FakeLLMProvider ran out of scripted responses after "
                f"{len(self.requests)} call(s) — the script is shorter than the "
                f"exchange under test"
            )
        return self._responses.popleft()

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def last_request(self) -> LLMRequest:
        if not self.requests:
            raise AssertionError("FakeLLMProvider has not been called yet")
        return self.requests[-1]


def final_text(text: str, *, usage: TokenUsage | None = None) -> LLMResponse:
    """An assistant turn that ends the phase with plain text (`stop_reason=end_turn`)."""
    return LLMResponse(
        text=text,
        tool_calls=[],
        stop_reason=StopReason.END_TURN,
        usage=usage or TokenUsage(),
        raw_content=[{"type": "text", "text": text}],
    )


def tool_call(
    name: str,
    *,
    call_id: str | None = None,
    usage: TokenUsage | None = None,
    **arguments: object,
) -> LLMResponse:
    """An assistant turn that calls one tool (`stop_reason=tool_use`)."""
    return tool_calls(
        ToolCall(id=call_id or _next_id(name), name=name, arguments=dict(arguments)),
        usage=usage,
    )


def tool_calls(*calls: ToolCall, usage: TokenUsage | None = None) -> LLMResponse:
    """A single assistant turn that batches several tool calls."""
    return LLMResponse(
        text="",
        tool_calls=list(calls),
        stop_reason=StopReason.TOOL_USE,
        usage=usage or TokenUsage(),
        raw_content=[
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in calls
        ],
    )


def refusal(text: str = "") -> LLMResponse:
    """An assistant turn the model declined to answer (`stop_reason=refusal`)."""
    return LLMResponse(
        text=text,
        tool_calls=[],
        stop_reason=StopReason.REFUSAL,
        usage=TokenUsage(),
        raw_content=[],
    )


def _next_id(name: str) -> str:
    return f"toolu_fake_{name}_{uuid4().hex[:8]}"
