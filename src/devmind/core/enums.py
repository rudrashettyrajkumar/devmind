"""Closed-set values used throughout DevMind.

Every field with a fixed set of valid values is a `StrEnum` here — never a bare string.
Behaviour that belongs to a value (e.g. "is this status terminal?") lives on the enum
itself, not scattered through the services that consume it.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final


class SessionStatus(StrEnum):
    """The lifecycle of one DevMind session. See docs/01-solution-design.md §5.

    The legal-transition map (`_LEGAL_TRANSITIONS`, below) lives in this module rather
    than in `services/session_state_machine.py` — deliberately, deviating from the
    literal code sample in `docs/specs/epic-02-session-domain-persistence.md`, which
    shows it co-located with `SessionStateMachine`. Keeping it here instead means
    `core/` never has to import `services/` for `can_transition_to()` to work
    (Claude.md §1 layer rule) — the decision (and the stub this completes) was already
    made and tested in E1. `SessionStateMachine` (E2, `services/`) is the only place
    that *acts* on a transition — persisting it and emitting the event; this method is
    purely the question "is this move legal," answerable with no I/O.
    """

    CREATED = "created"
    INGESTING = "ingesting"
    PLANNING = "planning"
    INVESTIGATING = "investigating"
    EDITING = "editing"
    TESTING = "testing"
    SUMMARIZING = "summarizing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    PR_OPENED = "pr_opened"
    REJECTED = "rejected"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    HALTED = "halted"

    def is_terminal(self) -> bool:
        """True for a status the session never leaves."""
        return self in _TERMINAL_STATUSES

    def can_transition_to(self, target: "SessionStatus") -> bool:
        """Whether `target` is a legal next status from here."""
        return target in _LEGAL_TRANSITIONS.get(self, frozenset())


_TERMINAL_STATUSES: Final[frozenset[SessionStatus]] = frozenset(
    {
        SessionStatus.PR_OPENED,
        SessionStatus.REJECTED,
        SessionStatus.EXHAUSTED,
        SessionStatus.FAILED,
        SessionStatus.HALTED,
    }
)

# The single source of truth for what the orchestrator is allowed to do next
# (docs/01-solution-design.md §5). A status with no entry here — every terminal
# status — accepts nothing, via the `.get(self, frozenset())` default above.
_LEGAL_TRANSITIONS: Final[Mapping[SessionStatus, frozenset[SessionStatus]]] = {
    SessionStatus.CREATED: frozenset(
        {SessionStatus.INGESTING, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.INGESTING: frozenset(
        {SessionStatus.PLANNING, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.PLANNING: frozenset(
        {SessionStatus.INVESTIGATING, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.INVESTIGATING: frozenset(
        {SessionStatus.EDITING, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.EDITING: frozenset(
        {SessionStatus.TESTING, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.TESTING: frozenset(
        {
            SessionStatus.EDITING,
            SessionStatus.SUMMARIZING,
            SessionStatus.EXHAUSTED,
            SessionStatus.FAILED,
            SessionStatus.HALTED,
        }
    ),
    SessionStatus.SUMMARIZING: frozenset(
        {SessionStatus.AWAITING_APPROVAL, SessionStatus.FAILED, SessionStatus.HALTED}
    ),
    SessionStatus.AWAITING_APPROVAL: frozenset(
        {SessionStatus.APPROVED, SessionStatus.REJECTED, SessionStatus.HALTED}
    ),
    # APPROVED intentionally omits HALTED: once a human has approved, the only
    # remaining moves are opening the PR or a delivery failure (E10) — cancellation
    # is a concept for in-flight agent work, not a post-approval state.
    SessionStatus.APPROVED: frozenset({SessionStatus.PR_OPENED, SessionStatus.FAILED}),
    # Every terminal status (PR_OPENED, REJECTED, EXHAUSTED, FAILED, HALTED) has no
    # entry — and therefore no legal outbound transition. This is also what makes
    # PR_OPENED reachable only from APPROVED: it appears as a target in exactly one
    # value above.
}


class EventType(StrEnum):
    """Every kind of entry that can appear in a session's append-only event log."""

    SESSION_CREATED = "session_created"
    STATE_CHANGED = "state_changed"
    INGESTION_STEP = "ingestion_step"
    PLAN_UPDATED = "plan_updated"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEST_RUN = "test_run"
    FIX_ATTEMPT = "fix_attempt"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    PR_OPENED = "pr_opened"
    SESSION_FAILED = "session_failed"


class TodoStatus(StrEnum):
    """Status of one item on the agent's plan."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"


class ApprovalDecision(StrEnum):
    """The human's verdict on an `AWAITING_APPROVAL` session."""

    APPROVED = "approved"
    REJECTED = "rejected"


class CorrectionAction(StrEnum):
    """`SelfCorrectionController.decide()`'s verdict on a parsed test run (E8).

    `SUCCEEDED` and `EXHAUSTED` are terminal for the self-correction loop — the
    orchestrator moves to `SUMMARIZING` or the terminal `EXHAUSTED` session status
    respectively. `RETRY` sends it back through `EDITING` with the failure report as
    context, and only until `MAX_FIX_ATTEMPTS` or a repeated failure signature.
    """

    SUCCEEDED = "succeeded"
    RETRY = "retry"
    EXHAUSTED = "exhausted"


class SandboxBackend(StrEnum):
    """Which sandbox implementation a session runs commands in.

    `AUTO` is resolved once at startup by `SandboxFactory` (E5) and the resolved value
    (never `AUTO` itself) is what gets persisted on the session record.
    """

    AUTO = "auto"
    DOCKER = "docker"
    SUBPROCESS = "subprocess"


class AgentPhase(StrEnum):
    """Which phase of the loop the agent is currently executing (E7)."""

    PLANNING = "planning"
    INVESTIGATION = "investigation"
    EDITING = "editing"
    TESTING = "testing"
    SUMMARIZING = "summarizing"


class LoopStatus(StrEnum):
    """How one `AgentLoop.run()` over a single phase ended (E7).

    `COMPLETED` covers both a clean `end_turn` and an explicit `finish` call — the
    difference (a `finish_summary` and `confidence`) is carried on `LoopOutcome`, not
    encoded here. `BUDGET_EXHAUSTED` is the step ceiling; the cost ceiling raises
    `BudgetExceededError` instead of returning, because it is a session-wide fault the
    loop cannot recover from. `CANCELLED` is a cooperative stop the orchestrator asked
    for; `FAILED` is the model refusing or otherwise ending the phase unusably.
    """

    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ToolName(StrEnum):
    """Every tool the agent may call. The registry (E6) is the source of truth for
    which are actually registered in a given phase; this enum is the closed set of
    valid names so a typo in a tool call is a type error, not a runtime surprise.
    """

    LIST_DIR = "list_dir"
    READ_FILE = "read_file"
    SEARCH_CODE = "search_code"
    FIND_SYMBOL = "find_symbol"
    WRITE_FILE = "write_file"
    APPLY_PATCH = "apply_patch"
    RUN_COMMAND = "run_command"
    RUN_TESTS = "run_tests"
    GIT_DIFF = "git_diff"
    TODO_WRITE = "todo_write"
    FINISH = "finish"


# The tool subset each phase runs with (E7 §SessionOrchestrator, design §6.2). This
# is the structural half of "investigation cannot write": the phase is handed only
# these schemas, and `AgentLoop` refuses any call outside the set — a property, not a
# prompt instruction. `TODO_WRITE` and `FINISH` are in every phase because every
# phase maintains the plan and ends with an explicit `finish`. Keyed on the loop
# phases only; `PLANNING` runs through `PlannerService`, not the loop, and
# `SUMMARIZING` belongs to a later epic.
_READ_ONLY_TOOLS: Final[frozenset[ToolName]] = frozenset(
    {
        ToolName.LIST_DIR,
        ToolName.READ_FILE,
        ToolName.SEARCH_CODE,
        ToolName.FIND_SYMBOL,
        ToolName.GIT_DIFF,
        ToolName.TODO_WRITE,
        ToolName.FINISH,
    }
)
_EDIT_TOOLS: Final[frozenset[ToolName]] = _READ_ONLY_TOOLS | {
    ToolName.WRITE_FILE,
    ToolName.APPLY_PATCH,
    ToolName.RUN_COMMAND,
    ToolName.RUN_TESTS,
}
TOOLS_BY_PHASE: Final[Mapping[AgentPhase, frozenset[ToolName]]] = {
    AgentPhase.INVESTIGATION: _READ_ONLY_TOOLS,
    AgentPhase.EDITING: _EDIT_TOOLS,
}


class Effort(StrEnum):
    """Reasoning-effort levels for an LLM call — Claude Opus 5's `output_config.effort`.

    A closed set (Claude.md §6): the API rejects anything else with a 400. `HIGH` is
    the model default and DevMind's default for the agent loop; `LOW` is for cheap
    classification-style calls (docs/01-solution-design.md §6.1). Typed as a `StrEnum`
    rather than the bare `str` the E3 spec sketches, for consistency with `StopReason`
    and the standards — see the epic report's deviations.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class StopReason(StrEnum):
    """Normalized `stop_reason` values from an LLM response (see schemas/llm.py)."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"
    STOP_SEQUENCE = "stop_sequence"


class GitFailureReason(StrEnum):
    """Why a git / PR delivery step failed (E10).

    Each value is a distinct, human-actionable outcome — the session moves to
    `FAILED` carrying one of these and the branch is retained locally. Nothing here
    is ever retried against a remote (spec §"Failure handling"): a failed push is a
    human's decision, not a loop's.
    """

    BRANCH_CREATE_FAILED = "branch_create_failed"
    COMMIT_FAILED = "commit_failed"
    PUSH_REJECTED = "push_rejected"
    NO_PUSH_PERMISSION = "no_push_permission"
    REMOTE_BRANCH_EXISTS = "remote_branch_exists"
    PR_CREATE_FAILED = "pr_create_failed"


class IssueState(StrEnum):
    """The state of a GitHub issue, as reported by `gh issue view --json state`.

    `gh` emits `OPEN` / `CLOSED`; `GitHubClient` lower-cases before constructing this
    so the closed set here stays in DevMind's convention (lower-case StrEnum values,
    like every other enum in this module).
    """

    OPEN = "open"
    CLOSED = "closed"


class SymbolKind(StrEnum):
    """What kind of definition a `Symbol` in the code index points at (E4).

    Two values is enough for navigation — "where is X defined" only needs to
    distinguish a type from a callable. The Python AST walk and the non-Python regex
    fallback both map onto these.
    """

    CLASS = "class"
    FUNCTION = "function"


class TestFramework(StrEnum):
    """A repository's test framework, detected during ingestion (E4).

    v1 only detects `pytest` (docs/01-solution-design.md §2 — Python/pytest target),
    but this is a genuinely open set the moment language #2 lands, and the value is
    referenced across several detection branches and again in E8's argv assembly, so
    it is an enum rather than the bare `str` the spec sketch shows. `None` — no
    framework detected — stays a legitimate outcome carried alongside it.
    """

    PYTEST = "pytest"


class DependencyManager(StrEnum):
    """A repository's dependency manager, detected during ingestion (E4).

    Drives `RepoProfile.install_command`. A closed, typo-prone set consumed by more
    than one detection branch — enum, not bare string (Claude.md §6).
    """

    UV = "uv"
    POETRY = "poetry"
    PIP = "pip"


class IngestionStep(StrEnum):
    """The ordered steps `RepoIngestionService` walks, one `INGESTION_STEP` event each.

    The values land in the event payload that session replay reads, so they are a
    closed set — a `StrEnum`, not inline literals scattered through `_emit` calls.
    """

    WORKSPACE_CREATED = "workspace_created"
    CLONED = "cloned"
    ISSUE_RESOLVED = "issue_resolved"
    PROFILED = "profiled"
    INDEXED = "indexed"
