"""DTOs for the LLM provider seam.

Every caller depends on these typed shapes and on `LLMProvider`, never on the
`anthropic` SDK directly (Claude.md §2). See docs/specs/epic-03 §Contracts.
"""

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.constants import DEFAULT_CACHE_BREAKPOINTS, DEFAULT_LLM_MAX_TOKENS
from devmind.core.enums import Effort, StopReason


class ToolCall(BaseModel):
    """One `tool_use` block from an assistant turn, normalized.

    `arguments` is the parsed object (the provider runs `json.loads` when the SDK
    hands back a string), never a string for a caller to pattern-match.
    """

    id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    """A tool's outcome, shaped for the next user turn's content. A failed tool is
    still returned — with `is_error=True` and a readable `content` — never dropped.
    """

    model_config = ConfigDict(frozen=True)

    tool_use_id: str
    content: str
    is_error: bool = False


class TokenUsage(BaseModel):
    """Token counts for one response, straight from the API's `usage` block."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LLMRequest(BaseModel):
    """Everything one `LLMProvider.complete()` call needs.

    `messages` and `tools` stay as raw block dicts: they are the wire format handed
    straight to the provider, which is the single place allowed to translate them for
    the SDK. `system` and volatile per-step content that follows the cache prefix are
    the caller's responsibility to keep byte-stable across a session.
    """

    system: str
    messages: list[dict[str, object]]
    tools: list[dict[str, object]] = Field(default_factory=list)
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    effort: Effort = Effort.HIGH
    cache_breakpoints: int = Field(default=DEFAULT_CACHE_BREAKPOINTS, ge=0, le=4)
    enable_context_editing: bool = False


class LLMResponse(BaseModel):
    """One assistant turn, normalized.

    `raw_content` is the SDK's content blocks as plain JSON dicts. Append it back
    **verbatim** as the assistant message on the next turn — thinking blocks and their
    signatures included; rebuilding it from `text` loses state (docs/specs/epic-03
    §Contracts).
    """

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason
    usage: TokenUsage
    raw_content: list[dict[str, object]]
