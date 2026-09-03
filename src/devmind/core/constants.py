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

# --- Test execution (E8) -------------------------------------------------------
# Appended to `RepoProfile.test_command` on every run: quiet output, short
# tracebacks, and no stale `.pytest_cache` carried between the baseline and an
# attempt (a cached last-failed set would silently narrow a "full" run).
PYTEST_EXECUTION_ARGS: Final[tuple[str, ...]] = ("-q", "--tb=short", "-p", "no:cacheprovider")
# `--timeout=<n>` is added only when the sandbox image ships `pytest-timeout`
# (`TestExecutionService(pytest_timeout_supported=True)`). The sandbox's own
# process-group kill (E5) is the real hang guard; this is a diagnostic nicety that
# names the culprit test instead of killing the whole run.
PYTEST_TIMEOUT_SECONDS: Final[int] = 240
# A parsed `TestFailure.traceback` keeps at most this many lines — enough to see the
# failing frame and the assertion, not a 200-line dump multiplied across the retry
# prompt.
TEST_FAILURE_TRACEBACK_MAX_LINES: Final[int] = 40
# Ceiling on one `TestFailure.message`.
TEST_FAILURE_MESSAGE_MAX_CHARS: Final[int] = 2_000
# Ceiling on the number of individual `TestFailure`s carried on a report — a run with
# hundreds of failures is a category error (bad baseline, wrong command), and the
# retry prompt only needs a representative sample.
TEST_FAILURE_MAX_ITEMS: Final[int] = 30

# --- Agent loop --------------------------------------------------------------------
# Also exposed as `Settings.max_agent_steps_per_phase` (defaults to this constant).
MAX_AGENT_STEPS_PER_PHASE: Final[int] = 40
MAX_TOOL_RESULT_CHARS: Final[int] = 20_000
MAX_TEST_OUTPUT_CHARS: Final[int] = 30_000
MAX_FILE_READ_LINES: Final[int] = 2_000
MAX_DIFF_CHARS: Final[int] = 100_000
DEFAULT_AGENT_MODEL: Final[str] = "claude-opus-5"
# Claude Opus 5's context window. `AgentContext.estimated_tokens` is measured against
# this; the compactor acts once usage crosses `CONTEXT_COMPACTION_THRESHOLD` of it.
AGENT_CONTEXT_WINDOW_TOKENS: Final[int] = 200_000
# Also exposed as `Settings.context_compaction_threshold`.
CONTEXT_COMPACTION_THRESHOLD: Final[float] = 0.7
# `AgentContext` estimates tokens at this many characters per token — deliberately
# conservative (real BPE averages ~3.5-4), so the compactor fires early rather than
# after an overflow. A rough gauge for a threshold check, never billed.
TOKEN_ESTIMATE_CHARS_PER_TOKEN: Final[int] = 4

# --- Planner (E7) ----------------------------------------------------------------
# A plan outside this band is a planning failure: one vague step ("fix the bug")
# carries no information, and a plan past the ceiling is unfocused. `PlannerService`
# retries once, then raises `PlanningError`.
PLANNER_MIN_ITEMS: Final[int] = 2
PLANNER_MAX_ITEMS: Final[int] = 12
# Each step must read as an instruction, not a label — reject anything shorter.
PLANNER_MIN_WORDS_PER_ITEM: Final[int] = 3

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
# Shell metacharacters rejected in `argv[0]` (the binary) as defence-in-depth (SI-8) —
# a legitimate binary name never contains one. They are NOT rejected in later argv
# entries: `python -c "import x; x.main()"` is a normal command and nothing here runs
# through a shell, so a `;` in an argument is just bytes handed to execve.
SHELL_METACHARACTERS: Final[frozenset[str]] = frozenset(";|&$`><()\n\r\t ")
# The one character rejected in ANY argv entry: a NUL is the C string terminator,
# cannot be passed through `execve`, and is never legitimate in an argument. Newlines
# are allowed — a multi-line `python -c "..."` script is a normal command.
FORBIDDEN_ARG_CHARACTERS: Final[frozenset[str]] = frozenset("\x00")

# --- Sandbox: environment scrubbing (SI-2) -----------------------------------------
# The ONLY host environment variables a sandboxed command inherits. Everything else
# is dropped so repo code cannot read the operator's credentials or config.
# `PYTHONPATH` is deliberately NOT here (the E5 spec lists it): inheriting the host's
# `PYTHONPATH` would let repo code import host-side packages, which the isolation is
# meant to prevent. A repo that needs its own path sets it via `SandboxCommand.env`.
SANDBOX_ENV_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "PYTHONHASHSEED"}
)
# Head+tail truncation marker for command output (E5-F1-T3). `{removed}` / `{total}`
# are filled with the real counts.
SANDBOX_TRUNCATION_MARKER: Final[str] = "\n... [truncated {removed} of {total} chars] ...\n"
# Decimal places kept on a `CommandResult.duration_seconds`.
DURATION_PRECISION_DIGITS: Final[int] = 3
# Forced into every sandbox environment. The empty-string token vars actively blank
# any credential that leaked in another way; the git vars make a network git op fail
# fast instead of prompting.
SANDBOX_ENV_OVERRIDES: Final[Mapping[str, str]] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GH_TOKEN": "",
    "GITHUB_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
# Host env var name-fragments that must never appear in a sandbox environment — the
# SI-2 safety test asserts against this set.
SANDBOX_FORBIDDEN_ENV_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {"TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL", "AWS_", "ANTHROPIC"}
)

# --- Sandbox: process control --------------------------------------------------------
# After a timeout SIGKILL, how long to wait for the process group to actually die
# before giving up on the reap.
SANDBOX_KILL_GRACE_SECONDS: Final[float] = 2.0

# --- Sandbox: Docker backend ------------------------------------------------------
DOCKER_WORKSPACE_MOUNT: Final[str] = "/workspace"
DOCKER_WORKSPACE_MOUNT_MODE: Final[str] = "rw"
DOCKER_MEM_LIMIT: Final[str] = "2g"
DOCKER_NANO_CPUS: Final[int] = 2_000_000_000  # 2.0 CPUs
DOCKER_PIDS_LIMIT: Final[int] = 512
DOCKER_CONTAINER_USER: Final[str] = "1000:1000"
DOCKER_IDLE_COMMAND: Final[tuple[str, ...]] = ("sleep", "infinity")
DOCKER_CAP_DROP: Final[tuple[str, ...]] = ("ALL",)
DOCKER_SECURITY_OPT: Final[tuple[str, ...]] = ("no-new-privileges",)
# `"none"` is SI-2 load-bearing — the session container gets no network namespace.
# `"bridge"` is used only by the throwaway dependency-install container.
DOCKER_NETWORK_ISOLATED: Final[str] = "none"
DOCKER_NETWORK_INSTALL: Final[str] = "bridge"

# --- Tools (E6) ------------------------------------------------------------------
# `list_dir` depth is capped low — the tool is for orientation, not a full crawl
# (that is `RepoBrief`, built once during ingestion).
LIST_DIR_MAX_DEPTH: Final[int] = 3
LIST_DIR_MAX_ENTRIES: Final[int] = 400
# `search_code` tool result cap (spec: `max_results <= 100`).
SEARCH_CODE_TOOL_MAX_RESULTS: Final[int] = 100
# `write_file` refuses a payload larger than this — a multi-megabyte write from the
# agent is a bug, not an edit.
WRITE_FILE_MAX_BYTES: Final[int] = 1_000_000
# `todo_write` plan-length ceiling — a plan longer than this is unfocused.
TODO_MAX_ITEMS: Final[int] = 40
# Characters of surrounding text `apply_patch` quotes when `old_string` is not found,
# so the model can see how close it got.
APPLY_PATCH_CONTEXT_CHARS: Final[int] = 240
# `apply_patch`'s near-miss anchor probe: shrink the first line of `old_string` by
# this ratio each attempt, down to this minimum length, looking for a fuzzy anchor.
APPLY_PATCH_MIN_ANCHOR_CHARS: Final[int] = 8
APPLY_PATCH_ANCHOR_SHRINK: Final[float] = 0.75
# `read_file` scans this many leading bytes for a NUL before deciding a file is binary.
READ_FILE_NULL_SCAN_BYTES: Final[int] = 8192

# --- Git / GitHub --------------------------------------------------------------------
BRANCH_PREFIX: Final[str] = "devmind"
# Fallback PR base branch when a session never recorded the repo's default branch.
DEFAULT_BASE_BRANCH: Final[str] = "main"
# The branch-name slug is lowercase ASCII, hyphen-separated, and capped here so a
# verbose issue title never produces an unwieldy ref (spec §BranchNamer).
BRANCH_SLUG_MAX_CHARS: Final[int] = 40
# A collision (`devmind/issue-42-fix-x` already taken) is resolved by appending
# `-2`, `-3`, … up to this many attempts before `BranchNamer` gives up.
BRANCH_COLLISION_MAX_SUFFIX: Final[int] = 50
# Wall-clock ceilings for the write-phase git / gh invocations (E10). Distinct from
# the read-phase `GIT_CLONE_*` / `GH_ISSUE_*` timeouts: a push or a `gh pr create`
# is a small, fast round-trip, and a hang here must not stall a session.
GIT_WRITE_OP_TIMEOUT_SECONDS: Final[int] = 60
GIT_PUSH_TIMEOUT_SECONDS: Final[int] = 120
GH_PR_CREATE_TIMEOUT_SECONDS: Final[int] = 60
# The commit body (the agent's change summary) is hard-wrapped at this column so the
# message reads well in `git log` and every GitHub view (spec §"Commit message").
COMMIT_BODY_WRAP_COLUMNS: Final[int] = 72
# Conventional-commit subject line: `<type>: <description>`, truncated to this length.
COMMIT_SUBJECT_MAX_CHARS: Final[int] = 72
COMMIT_SUBJECT_PREFIX: Final[str] = "fix: "
# Identity stamped on the commit DevMind creates. Attribution to the model and to the
# approving human is carried by the `Co-Authored-By` / `Approved-by` trailers; this
# is just the author/committer so the commit is not ascribed to whoever's shell ran.
AGENT_GIT_AUTHOR_NAME: Final[str] = "DevMind"
AGENT_GIT_AUTHOR_EMAIL: Final[str] = "devmind@users.noreply.github.com"
# The permanent trailers. `Co-Authored-By` puts the model on the change; `Approved-by`
# (filled with the deciding human's name) puts a person on it — that is the audit
# trail doing its job (spec §"Commit message").
COMMIT_COAUTHOR_TRAILER: Final[str] = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
# The load-bearing sentence in the PR body's provenance footer: a reviewer must never
# have to guess whether a human looked at this, or whether it was merged (spec §"PR body").
PR_BODY_DRAFT_NOTICE: Final[str] = "This PR is a draft and has not been merged."
# `PrBodyComposer` refuses a model-rendered body that is missing any of these — the
# provenance footer is then appended deterministically on top, never trusted to the
# model (spec §"PR body" — "The provenance footer is not optional").
PR_BODY_REQUIRED_HEADINGS: Final[tuple[str, ...]] = (
    "## Summary",
    "## The issue",
    "## Changes",
    "## Test evidence",
    "## Risks and what to review closely",
)
PR_BODY_PROVENANCE_HEADING: Final[str] = "## Provenance"
# Substituted for `{issue_reference}` when a session was started from free text rather
# than a GitHub issue number — the prompt drops the `Closes …` line on seeing it.
PR_BODY_NO_ISSUE_REFERENCE: Final[str] = "(no linked issue — session started from a description)"

# --- Approval gate & review payload (E9) -----------------------------------------
# Appended to a unified diff once it crosses `MAX_DIFF_CHARS` — a truncated diff is
# never presented to a reviewer as if it were complete (spec §DiffService).
DIFF_TRUNCATION_MARKER: Final[str] = (
    "\n... [diff truncated at {limit} chars — NOT the full change] ..."
)
# The load-bearing `ApprovalRequest.warnings` strings. Each is added verbatim, and
# only when its condition holds, by `ApprovalRequestBuilder`. A human skimming the
# payload must be unable to miss any of them (spec §"The review payload").
WARNING_UNVERIFIED_NO_TESTS: Final[str] = "UNVERIFIED — no test suite found in this repository"
WARNING_TESTS_ONLY_DIFF: Final[str] = "The diff modifies only test files"
WARNING_COST_CEILING: Final[str] = "Session hit its cost ceiling"
WARNING_SUBPROCESS_SANDBOX: Final[str] = (
    "Sandbox backend was `subprocess` — process isolation only, not a security boundary"
)
# Filenames / path fragments that mark a changed file as a test file for the
# tests-only-diff detection, on top of any `RepoProfile.test_paths` prefix.
TEST_PATH_FRAGMENTS: Final[frozenset[str]] = frozenset({"test", "tests", "conftest.py"})

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

# --- API & SSE (E11) ------------------------------------------------------------
API_V1_PREFIX: Final[str] = "/api/v1"
# `EventStreamService` polls the event table at this cadence. Half a second is the
# latency budget for one local process against a local database (spec §"SSE streaming").
SSE_POLL_INTERVAL_SECONDS: Final[float] = 0.5
# An SSE heartbeat comment at least this often so a proxy does not reap an idle
# connection during a long, quiet stretch of a run.
SSE_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 15.0
# Rows pulled per poll — a burst of events (tool calls) drains over a few polls
# rather than all at once.
SSE_STREAM_BATCH_LIMIT: Final[int] = 100
# Default page size for `GET /sessions` and `GET /sessions/{id}/events`.
API_DEFAULT_PAGE_LIMIT: Final[int] = 50
API_MAX_PAGE_LIMIT: Final[int] = 200
# Wall-clock ceiling on the host `git diff` behind `GET /sessions/{id}/diff`.
DIFF_ENDPOINT_TIMEOUT_SECONDS: Final[int] = 30

# --- Persistence -----------------------------------------------------------------
# EventRepository.append() allocates the next sequence with SELECT MAX(sequence)+1
# inside the same transaction as the insert, backstopped by a unique constraint on
# (session_id, sequence). Two attempts total: the first, and one retry on collision.
EVENT_SEQUENCE_MAX_ATTEMPTS: Final[int] = 2
