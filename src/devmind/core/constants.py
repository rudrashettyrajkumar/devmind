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

# --- Workspace (E4) ------------------------------------------------------------------
# Disk ceiling across ALL session workspaces under the root. `WorkspaceManager`
# refuses to create a new workspace once usage crosses this — a disk-full failure at
# minute nine of a run is a bad way to find out (spec §WorkspaceManager). Also
# exposed as `Settings.workspace_max_bytes` (defaults to this constant).
WORKSPACE_MAX_BYTES_DEFAULT: Final[int] = 5 * 1024**3  # 5 GiB

# --- Host command execution (E4) --------------------------------------------------
# `CommandRunner` runs `git` and `gh` on the host for read-phase ingestion — this is
# NOT the sandbox (that is E5). A wall-clock ceiling on every invocation so a hung
# `git` or `gh` never stalls a session.
COMMAND_RUNNER_DEFAULT_TIMEOUT_SECONDS: Final[int] = 120
GIT_CLONE_TIMEOUT_SECONDS: Final[int] = 300
GH_ISSUE_TIMEOUT_SECONDS: Final[int] = 30
# depth 50, not 1: `git diff` and blame-style investigation need a little history,
# and a full clone of a large repo is minutes wasted (spec §RepoIngestionService).
GIT_CLONE_DEPTH: Final[int] = 50
# Forced into every host `git`/`gh` environment: a private repo with no credential
# helper fails fast instead of blocking on an interactive prompt (SI-2, spec §Notes).
NON_INTERACTIVE_GIT_ENV: Final[Mapping[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GCM_INTERACTIVE": "never",
}
GITHUB_ISSUE_JSON_FIELDS: Final[str] = "number,title,body,labels,state"
# Exit code a `CommandRunner` reports when the binary itself is missing, mirroring the
# shell convention — callers branch on `CommandOutput.ok`, not on this value directly.
COMMAND_NOT_FOUND_EXIT_CODE: Final[int] = 127

# --- Code index (E4) -------------------------------------------------------------
REPO_TREE_MAX_DEPTH: Final[int] = 4
REPO_TREE_MAX_ENTRIES: Final[int] = 2_000
PYTEST_MODULE_INVOCATION: Final[tuple[str, ...]] = ("python", "-m", "pytest")

# `RepoProfile.language` is an open-ended `str` (not an enum), but the values the
# profiler actually emits live here so they are not typed inline in more than one
# branch of the detection logic.
LANGUAGE_PYTHON: Final[str] = "python"
LANGUAGE_UNKNOWN: Final[str] = "unknown"
LANGUAGE_BY_SOURCE_SUFFIX: Final[Mapping[str, str]] = {
    ".py": LANGUAGE_PYTHON,
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".rs": "rust",
}
# Directories never walked by the tree builder or the symbol indexer, regardless of
# `.gitignore` — build artefacts, VCS internals, vendored deps, tool caches.
INDEX_IGNORE_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "dist",
        "build",
        ".eggs",
        ".idea",
        ".vscode",
        "htmlcov",
    }
)
# Suffixes treated as binary: never opened for symbol extraction, never counted as
# source when detecting a repo's language.
BINARY_FILE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".o",
        ".a",
        ".dll",
        ".dylib",
        ".class",
        ".jar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".wav",
        ".bin",
        ".exe",
        ".wasm",
        ".lock",
    }
)
# Non-Python source suffixes that get the regex symbol fallback (spec §SymbolIndexer).
REGEX_SYMBOL_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rb",
        ".java",
        ".kt",
        ".rs",
        ".c",
        ".h",
        ".cc",
        ".hpp",
        ".cpp",
        ".cs",
        ".php",
        ".swift",
        ".scala",
    }
)

# --- Code search (E4) ----------------------------------------------------------------
CODE_SEARCH_MAX_RESULTS: Final[int] = 200
# One unlucky minified line can't blow the context window (spec §CodeSearchService).
CODE_SEARCH_MAX_LINE_CHARS: Final[int] = 500
CODE_SEARCH_TIMEOUT_SECONDS: Final[int] = 30

# --- Repo brief (E4) -----------------------------------------------------------------
# Hard ~2,000-token budget for the cacheable structural summary that sits in the
# system prefix (spec §RepoBrief), at a conservative ~4 chars/token.
REPO_BRIEF_MAX_CHARS: Final[int] = 8_000
REPO_BRIEF_TREE_DEPTH: Final[int] = 2
REPO_BRIEF_MAX_TREE_LINES: Final[int] = 60
REPO_BRIEF_MAX_KEY_MODULES: Final[int] = 12
REPO_BRIEF_MAX_ENTRY_POINTS: Final[int] = 8
# Filenames that mark an executable entry point when found at a repo's top level.
ENTRY_POINT_FILENAMES: Final[frozenset[str]] = frozenset(
    {"__main__.py", "main.py", "manage.py", "app.py", "wsgi.py", "asgi.py", "cli.py"}
)

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
