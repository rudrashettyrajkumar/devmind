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
