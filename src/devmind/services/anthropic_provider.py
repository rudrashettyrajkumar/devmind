"""The production `LLMProvider`: a thin, typed wrapper over the `anthropic` async SDK.

This is the **only** module in DevMind that imports `anthropic` (an E3 acceptance
criterion). Everything above it depends on `LLMProvider` and the `schemas/llm.py`
DTOs. Streaming, prompt-cache breakpoint placement, the beta context-editing
strategy, and SDK-error translation all live here as implementation detail.

Tests inject an already-constructed `AsyncAnthropic` (a fake); production calls
`AnthropicProvider.from_settings()`, which builds a real client here — with
`max_retries` set (the SDK's own backoff for connection errors and 408/409/429/5xx)
rather than a second retry loop — so `anthropic` stays imported in this one module.
"""

from __future__ import annotations

import json
import logging
from typing import Final, cast

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import (
    Message,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    ThinkingConfigParam,
    ToolUnionParam,
)
from anthropic.types.beta import (
    BetaContextManagementConfigParam,
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaThinkingConfigParam,
)

from devmind.core.config import Settings
from devmind.core.constants import (
    STREAMING_MAX_TOKENS_THRESHOLD,
    SUSTAINED_ZERO_CACHE_READ_CALLS,
)
from devmind.core.enums import StopReason
from devmind.exceptions import LLMProviderError
from devmind.interfaces.llm_provider import LLMProvider
from devmind.schemas.llm import LLMRequest, LLMResponse, TokenUsage, ToolCall
from devmind.services.cost_calculator import CostCalculator

logger = logging.getLogger(__name__)

_CONTEXT_EDITING_BETA: Final = "context-management-2025-06-27"
_CLEAR_TOOL_USES_STRATEGY: Final = "clear_tool_uses_20250919"
_SYSTEM_CACHE_MIN_BREAKPOINTS: Final[int] = 1
_TOOLS_CACHE_MIN_BREAKPOINTS: Final[int] = 2
_RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({408, 409, 429})
# The SDK's own retry budget for connection errors and 408/409/429/5xx. Kept here,
# with the only `anthropic` import, so `Container` never has to touch the SDK to
# build a client (enforced by test_anthropic_is_imported_in_exactly_one_src_module).
_SDK_MAX_RETRIES: Final[int] = 3


class AnthropicProvider(LLMProvider):
    """Calls Claude Opus 5 with adaptive thinking and effort-controlled depth."""

    def __init__(self, client: AsyncAnthropic, settings: Settings, cost: CostCalculator) -> None:
        self._client = client
        self._settings = settings
        self._cost = cost
        self._call_count = 0
        self._zero_cache_read_streak = 0

    @classmethod
    def from_settings(cls, settings: Settings, cost: CostCalculator) -> AnthropicProvider:
        """Build a provider with a real `AsyncAnthropic` client from `settings`.

        The composition root (`Container`) calls this instead of constructing the SDK
        client itself, so `anthropic` stays imported in exactly one module.
        """
        client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=_SDK_MAX_RETRIES)
        return cls(client, settings, cost)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            message = await self._dispatch(request)
        except anthropic.NotFoundError as exc:
            raise LLMProviderError(
                "Anthropic API: model not found — check `agent_model`",
                details={"model": self._settings.agent_model, "retryable": False},
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError(
                "Anthropic API: rate limited",
                details={"retryable": True, "retry_after": self._retry_after(exc)},
            ) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in _RETRYABLE_STATUS_CODES
            raise LLMProviderError(
                f"Anthropic API: HTTP {exc.status_code}",
                details={"retryable": retryable, "status_code": exc.status_code},
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError(
                "Anthropic API: connection error", details={"retryable": True}
            ) from exc
        except anthropic.APIError as exc:
            # Least-specific link: no raw SDK exception (e.g. APIResponseValidationError)
            # escapes past this seam — callers depend only on LLMProviderError.
            raise LLMProviderError(
                "Anthropic API: unexpected SDK error", details={"retryable": False}
            ) from exc

        response = self._to_response(message)
        self._record_call(response.usage)
        return response

    # --- request construction ---------------------------------------------------

    async def _dispatch(self, request: LLMRequest) -> Message | BetaMessage:
        system = self._system_blocks(request)
        messages = self._messages(request)
        tools = self._tool_blocks(request)
        thinking: ThinkingConfigParam = {"type": "adaptive"}
        output_config = self._output_config(request)
        should_stream = request.max_tokens > STREAMING_MAX_TOKENS_THRESHOLD

        if request.enable_context_editing:
            return await self._dispatch_with_context_editing(
                request, system, messages, tools, thinking, output_config, should_stream
            )
        if should_stream:
            async with self._client.messages.stream(
                model=self._settings.agent_model,
                max_tokens=request.max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                thinking=thinking,
                output_config=output_config,
            ) as stream:
                return await stream.get_final_message()
        return await self._client.messages.create(
            model=self._settings.agent_model,
            max_tokens=request.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking=thinking,
            output_config=output_config,
        )

    async def _dispatch_with_context_editing(
        self,
        request: LLMRequest,
        system: list[TextBlockParam],
        messages: list[MessageParam],
        tools: list[ToolUnionParam],
        thinking: ThinkingConfigParam,
        output_config: OutputConfigParam,
        should_stream: bool,
    ) -> BetaMessage:
        context_management: BetaContextManagementConfigParam = {
            "edits": [{"type": _CLEAR_TOOL_USES_STRATEGY}]
        }
        betas: list[str] = [_CONTEXT_EDITING_BETA]
        # The beta namespace mirrors the stable one but re-exports its param TypedDicts
        # under `Beta*` names; these three are structurally identical, so re-narrow
        # rather than rebuild.
        beta_messages = cast("list[BetaMessageParam]", messages)
        beta_thinking = cast("BetaThinkingConfigParam", thinking)
        beta_output_config = cast("BetaOutputConfigParam", output_config)
        if should_stream:
            async with self._client.beta.messages.stream(
                model=self._settings.agent_model,
                max_tokens=request.max_tokens,
                system=system,
                messages=beta_messages,
                tools=tools,
                thinking=beta_thinking,
                output_config=beta_output_config,
                context_management=context_management,
                betas=betas,
            ) as stream:
                return await stream.get_final_message()
        return await self._client.beta.messages.create(
            model=self._settings.agent_model,
            max_tokens=request.max_tokens,
            system=system,
            messages=beta_messages,
            tools=tools,
            thinking=beta_thinking,
            output_config=beta_output_config,
            context_management=context_management,
            betas=betas,
        )

    def _system_blocks(self, request: LLMRequest) -> list[TextBlockParam]:
        """The cacheable system prefix.

        One block today (the whole `system` string), kept as a list so E4's repo
        brief can be appended as a second block without changing this call site. The
        cache breakpoint goes on the **last** block only, and only volatile-free
        content ever reaches here — `LLMRequest.system` is a plain string the caller
        keeps byte-stable.
        """
        block: TextBlockParam = {"type": "text", "text": request.system}
        if request.cache_breakpoints >= _SYSTEM_CACHE_MIN_BREAKPOINTS:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _tool_blocks(self, request: LLMRequest) -> list[ToolUnionParam]:
        """Tool schemas passed straight through from the registry.

        A second cache breakpoint lands on the last tool when
        `cache_breakpoints >= 2`, so a change to `system` alone still leaves the
        (larger) tools segment cached. The registry must build these byte-identically
        for the life of a session.
        """
        blocks: list[dict[str, object]] = [dict(tool) for tool in request.tools]
        if blocks and request.cache_breakpoints >= _TOOLS_CACHE_MIN_BREAKPOINTS:
            blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        # The registry (E6) produces validated tool schemas; the provider is the seam
        # that hands them to the SDK's param type.
        return cast("list[ToolUnionParam]", blocks)

    @staticmethod
    def _messages(request: LLMRequest) -> list[MessageParam]:
        # `LLMRequest.messages` is the wire format by design (schemas/llm.py); this is
        # the one place it is re-typed for the SDK.
        return cast("list[MessageParam]", request.messages)

    @staticmethod
    def _output_config(request: LLMRequest) -> OutputConfigParam:
        # `Effort`'s values are exactly `OutputConfigParam`'s accepted literals; the
        # enum is the project-wide closed set (Claude.md §6) and this re-narrows it.
        return cast("OutputConfigParam", {"effort": request.effort.value})

    # --- response parsing -----------------------------------------------------------

    def _to_response(self, message: Message | BetaMessage) -> LLMResponse:
        payload = message.model_dump(mode="json")
        raw_content = self._raw_content(payload)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in raw_content:
            block_type = block.get("type")
            if block_type == "text":
                value = block.get("text")
                if isinstance(value, str):
                    text_parts.append(value)
            elif block_type == "tool_use":
                tool_calls.append(self._tool_call(block))

        stop_reason = self._stop_reason(payload.get("stop_reason"))
        if stop_reason is StopReason.REFUSAL:
            logger.warning("Anthropic API returned stop_reason=refusal for this request")

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=self._usage(payload.get("usage")),
            raw_content=raw_content,
        )

    @staticmethod
    def _raw_content(payload: dict[str, object]) -> list[dict[str, object]]:
        content = payload.get("content")
        if not isinstance(content, list):
            return []
        blocks: list[dict[str, object]] = []
        for item in content:
            if isinstance(item, dict):
                blocks.append({str(key): value for key, value in item.items()})
        return blocks

    def _tool_call(self, block: dict[str, object]) -> ToolCall:
        raw_id = block.get("id")
        raw_name = block.get("name")
        if not isinstance(raw_id, str) or not isinstance(raw_name, str):
            raise LLMProviderError(
                "malformed tool_use block: missing id or name",
                details={"block": block},
            )
        return ToolCall(
            id=raw_id, name=raw_name, arguments=self._coerce_arguments(block.get("input"))
        )

    @staticmethod
    def _coerce_arguments(raw: object) -> dict[str, object]:
        """Tool inputs are parsed, never string-matched — Opus 5 varies JSON escaping."""
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(
                    "tool_use.input was a string but not valid JSON",
                    details={"input": raw},
                ) from exc
        if isinstance(raw, dict):
            return {str(key): value for key, value in raw.items()}
        raise LLMProviderError(
            "tool_use.input did not decode to a JSON object",
            details={"input": repr(raw)},
        )

    @staticmethod
    def _usage(raw: object) -> TokenUsage:
        data = raw if isinstance(raw, dict) else {}

        def _count(key: str) -> int:
            value = data.get(key)
            return value if isinstance(value, int) else 0

        return TokenUsage(
            input_tokens=_count("input_tokens"),
            output_tokens=_count("output_tokens"),
            cache_read_input_tokens=_count("cache_read_input_tokens"),
            cache_creation_input_tokens=_count("cache_creation_input_tokens"),
        )

    @staticmethod
    def _stop_reason(raw: object) -> StopReason:
        if isinstance(raw, str):
            try:
                return StopReason(raw)
            except ValueError:
                logger.warning(
                    "unrecognized stop_reason %r from the API; treating as end_turn", raw
                )
        elif raw is not None:
            logger.warning("non-string stop_reason %r from the API; treating as end_turn", raw)
        return StopReason.END_TURN

    @staticmethod
    def _retry_after(exc: anthropic.RateLimitError) -> str | None:
        return exc.response.headers.get("retry-after")

    # --- observability ------------------------------------------------------------

    def _record_call(self, usage: TokenUsage) -> None:
        self._call_count += 1
        cost = self._cost.cost_for(self._settings.agent_model, usage)
        logger.info(
            "llm call #%d: input=%d output=%d cache_read=%d cache_write=%d cost=$%.4f",
            self._call_count,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_input_tokens,
            usage.cache_creation_input_tokens,
            cost,
        )
        if self._call_count == 1:
            return
        if usage.cache_read_input_tokens == 0:
            self._zero_cache_read_streak += 1
            if self._zero_cache_read_streak >= SUSTAINED_ZERO_CACHE_READ_CALLS:
                logger.warning(
                    "cache_read_input_tokens has been zero for %d consecutive calls "
                    "after the first — a volatile value has likely entered the cached "
                    "prefix (tools/system). See docs/specs/epic-03 §Prompt caching.",
                    self._zero_cache_read_streak,
                )
        else:
            self._zero_cache_read_streak = 0
