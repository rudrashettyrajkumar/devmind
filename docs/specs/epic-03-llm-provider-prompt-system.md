# Spec — E3: LLM Provider & Prompt System

| | |
|---|---|
| **Epic** | E3 |
| **Depends on** | E1, E2 |
| **Blocks** | E6, E7, E8, E9 |
| **Size** | L (~2 days) |
| **Skills** | `devmind-standards`, `devmind-prompt-authoring`, `devmind-testing` |

## Purpose

One typed seam to Claude, and every prompt in markdown. The `FakeLLMProvider` built here is
what makes the rest of the project deterministically testable — it is as much a deliverable as
the real provider.

## Design references

`docs/01-solution-design.md` §6.1 (context management), §13 (prompt system), §15 (cost).

## Contracts

### `interfaces/llm_provider.py`

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
```

One method. Resist widening it — streaming, caching, and retries are implementation details of
`AnthropicProvider`, not shape the callers need to know about.

### `schemas/llm.py`

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, object]          # parsed with json.loads, never string-matched

class ToolResultBlock(BaseModel):
    tool_use_id: str
    content: str
    is_error: bool = False

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

class LLMRequest(BaseModel):
    system: str
    messages: list[dict[str, object]]
    tools: list[dict[str, object]] = []
    max_tokens: int = 16_000
    effort: str = "high"
    cache_breakpoints: int = 2
    enable_context_editing: bool = False

class LLMResponse(BaseModel):
    text: str
    tool_calls: list[ToolCall] = []
    stop_reason: StopReason
    usage: TokenUsage
    raw_content: list[dict[str, object]]   # echoed back verbatim on the next turn
```

`raw_content` matters: assistant content blocks (including thinking blocks) must be appended
back **unchanged** on the following turn. Reconstructing them from `text` loses state.

### `services/anthropic_provider.py`

```python
class AnthropicProvider(LLMProvider):
    def __init__(self, client: AsyncAnthropic, settings: Settings,
                 cost: CostCalculator) -> None: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
```

Request construction — these are current-API facts; getting them wrong is a 400 or a silent
quality loss:

```python
kwargs = {
    "model": self._settings.agent_model,          # claude-opus-5
    "max_tokens": request.max_tokens,
    "system": self._build_system_blocks(request), # list of blocks, cache_control on the last
    "messages": request.messages,
    "tools": request.tools,
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": request.effort},
}
```

- **No `temperature`, `top_p`, `top_k`** — removed on this model family, returns 400.
- **No `budget_tokens`** — removed, returns 400. Depth is controlled by `effort`.
- **No assistant prefill** — returns 400.
- **Stream** when `max_tokens` is large; use `.get_final_message()` rather than hand-rolling
  event accumulation.
- Guard `stop_reason` before reading content; handle `refusal` explicitly rather than treating
  it as an error.

Error handling is a **chain**, most specific first — one broad `except APIStatusError` throws
away the retryable/non-retryable distinction:

```python
try:
    ...
except anthropic.NotFoundError as exc:      # bad model id — not retryable
    raise LLMProviderError("model not found", details={...}) from exc
except anthropic.RateLimitError as exc:     # retryable, honour retry-after
    ...
except anthropic.APIStatusError as exc:     # 4xx/5xx split on status
    ...
except anthropic.APIConnectionError as exc: # retryable
    ...
```

The SDK already retries connection errors, 408/409/429/5xx with backoff (default 2). Configure
`max_retries` on the client rather than writing a second retry loop on top.

### Prompt caching (`E3-F2-T1`)

Render order is `tools` → `system` → `messages`; a byte change anywhere in the prefix
invalidates everything after it. So:

- System blocks: `[identity_and_rules, repo_brief]`, `cache_control: {"type": "ephemeral"}` on
  the **last** block.
- **Never** interpolate a timestamp, step counter, or uuid into a system block. Volatile values
  go into the trailing user message.
- Tool definitions are built once per session and reused byte-identically — regenerating them
  per call with a dict that iterates in a different order silently kills the cache.
- Log `usage.cache_read_input_tokens` every call. A sustained zero after the first call is a bug
  to hunt, not a curiosity.

### `CostCalculator`

```python
class CostCalculator:
    def __init__(self, pricing: Mapping[str, ModelPrice] = MODEL_PRICING) -> None: ...
    def cost_for(self, model: str, usage: TokenUsage) -> float: ...
```

Cache reads are billed at `CACHE_READ_DISCOUNT` of the input rate. An unknown model raises
`ConfigurationError` rather than silently costing zero — a cost ceiling that reads zero is worse
than no ceiling.

### `FakeLLMProvider` (`tests/fakes/`)

Scripted responses in order, every request recorded. Raises a clear `AssertionError` when the
script runs dry — a mystery hang in an agent-loop test is expensive to debug. Ship the
`tool_call(...)` / `final_text(...)` builders alongside it; they are what make the loop tests
readable.

### `prompts/loader.py`

```python
class PromptLoader:
    def __init__(self, prompts_dir: Path) -> None: ...
    def load(self, name: str) -> LoadedPrompt: ...          # cached
    def render(self, name: str, **variables: object) -> str:
        """Raises PromptVariableError on a missing or unexpected variable."""
```

Validation is the point: declared `variables` must exactly match what's passed and what the body
uses. A silently unrendered `{failure_report}` reaching the model is the kind of bug that costs
an hour and $2.

### The seven prompts

Author per the `devmind-prompt-authoring` skill: `system_agent`, `planner`, `investigation`,
`patch_author`, `test_failure_analysis`, `change_summary`, `pr_body`.

`system_agent` is the cached prefix and carries the agent's standing rules — including that it
has no ability to push or open a PR, and that a human reviews everything. State it as fact, not
prohibition: the capability genuinely does not exist in its tool list.

## Task plan

E3-F1-T1 … E3-F3-T4 from the breakdown. Schemas → ABC → provider → fake → caching/cost →
loader → prompts.

## Testing

| Test | Proves |
|---|---|
| `test_anthropic_provider.py` | Request shape: adaptive thinking present, no temperature/budget_tokens, effort in `output_config`; response parsed; usage extracted |
| `test_provider_errors.py` | Each SDK error class maps to the right `LLMProviderError`; retryables distinguished from non-retryables |
| `test_cache_placement.py` | `cache_control` lands on the last system block; no volatile value appears in any system block |
| `test_cost_calculator.py` | Known pricing math; cache discount; unknown model raises |
| `test_prompt_loader.py` | Loads, caches, validates; missing variable raises; extra variable raises |
| `test_prompt_contracts.py` | **Every** `prompts/*.md` loads, metadata validates, declared variables render |
| `test_no_prompts_in_python.py` | Greps `src/` for prompt-shaped string literals and fails on a hit |
| `test_fake_llm_provider.py` | Records requests; raises when the script is exhausted |

The provider tests mock the SDK client — no test in this repo ever calls the real API.

## Acceptance criteria

- [ ] `FakeLLMProvider` drives a scripted multi-tool exchange end to end.
- [ ] All seven prompts load and render; `test_prompt_contracts` passes.
- [ ] `test_no_prompts_in_python` passes — no prompt text in any `.py`.
- [ ] Cost is computed correctly including the cache-read discount.
- [ ] `anthropic` is imported in exactly one module.
- [ ] `make check` green.

## Notes

- **Do not** use the SDK's beta `tool_runner`. Design §6 records why: this project needs
  per-step event persistence, step budgets, checkpointing, and phase-swapped prompts. That
  decision is made; don't re-open it mid-build.
- Keep `context_management.edits` (beta `context-management-2025-06-27`) behind a setting,
  default off, and turn it on in E7 once the loop exists to exercise it.
