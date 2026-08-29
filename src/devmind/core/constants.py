"""Every literal used more than once, or that could plausibly need to change.

All `Final`. Business logic references these names, never a bare literal typed inline
(Claude.md §8). A tunable an operator would want to override per-deployment belongs in
`Settings` instead — see the note on `MAX_FIX_ATTEMPTS` below.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per 1M tokens for one model. Used only by `MODEL_PRICING` below — this is
    not a schema (no request/response ever carries it), so it stays a plain frozen
    dataclass rather than a Pydantic model.
    """

    input_per_mtok: float
    output_per_mtok: float


# --- Self-correction loop --------------------------------------------------------
# NOTE: also exposed as `Settings.max_fix_attempts`, which *defaults to* this
# constant. The constant is what business logic reads by default; the setting is the
# operator override. Never duplicate the literal `3` elsewhere.
MAX_FIX_ATTEMPTS: Final[int] = 3

# --- Agent loop --------------------------------------------------------------------
# Also exposed as `Settings.max_agent_steps_per_phase` (defaults to this constant).
MAX_AGENT_STEPS_PER_PHASE: Final[int] = 40
MAX_TOOL_RESULT_CHARS: Final[int] = 20_000
MAX_TEST_OUTPUT_CHARS: Final[int] = 30_000
MAX_FILE_READ_LINES: Final[int] = 2_000
MAX_DIFF_CHARS: Final[int] = 100_000
DEFAULT_AGENT_MODEL: Final[str] = "claude-opus-5"

# --- LLM provider ----------------------------------------------------------------
# Default per-call output ceiling and cache-breakpoint count for an `LLMRequest`.
DEFAULT_LLM_MAX_TOKENS: Final[int] = 16_000
DEFAULT_CACHE_BREAKPOINTS: Final[int] = 2
# Above this `max_tokens`, `AnthropicProvider` streams the call (via
# `.get_final_message()`) so a long generation never hits the SDK's HTTP timeout.
STREAMING_MAX_TOKENS_THRESHOLD: Final[int] = 8_000
# After the first call, this many consecutive responses with zero cache-read tokens
# trips `AnthropicProvider`'s "a volatile value entered the cached prefix" warning.
SUSTAINED_ZERO_CACHE_READ_CALLS: Final[int] = 3

# --- Sandbox -------------------------------------------------------------------------
# Also exposed as `Settings.sandbox_command_timeout_seconds` (defaults to this constant).
SANDBOX_COMMAND_TIMEOUT_SECONDS: Final[int] = 300
DEPENDENCY_INSTALL_TIMEOUT_SECONDS: Final[int] = 900
DOCKER_PROBE_TIMEOUT_SECONDS: Final[int] = 3
ALLOWED_COMMAND_BINARIES: Final[frozenset[str]] = frozenset(
    {
        "python",
        "python3",
        "pytest",
        "uv",
        "pip",
        "ruff",
        "mypy",
        "git",
        "ls",
        "cat",
    }
)

# --- Git / GitHub --------------------------------------------------------------------
BRANCH_PREFIX: Final[str] = "devmind"

# --- Cost accounting -------------------------------------------------------------------
MODEL_PRICING: Final[Mapping[str, ModelPrice]] = {
    "claude-opus-5": ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0),
    "claude-sonnet-5": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
}
CACHE_READ_DISCOUNT: Final[float] = 0.1
# Cache *writes* are billed above the base input rate; cache *reads* below it
# (`CACHE_READ_DISCOUNT`). `CostCalculator` applies both.
CACHE_WRITE_MULTIPLIER: Final[float] = 1.25

# --- Persistence -----------------------------------------------------------------
# EventRepository.append() allocates the next sequence with SELECT MAX(sequence)+1
# inside the same transaction as the insert, backstopped by a unique constraint on
# (session_id, sequence). Two attempts total: the first, and one retry on collision.
EVENT_SEQUENCE_MAX_ATTEMPTS: Final[int] = 2
