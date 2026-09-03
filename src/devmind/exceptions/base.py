"""The DevMind exception hierarchy.

Every error this application raises is a `DevMindError`. Each subclass carries the
HTTP status it maps to, so the mapping lives with the exception (single source of
truth) instead of being duplicated in a router's `except` block. `api/errors.py` (E1)
reads `.http_status` off whatever it catches.
"""

from typing import Final


class DevMindError(Exception):
    """Base for everything this application raises. Never raise a bare `Exception`."""

    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: Final[dict[str, object]] = details or {}


class ConfigurationError(DevMindError):
    """A setting is missing, invalid, or contradicts another setting."""

    http_status = 500


class WorkspaceError(DevMindError):
    """A workspace could not be created, resolved, or torn down."""

    http_status = 500


class PathEscapeError(WorkspaceError):
    """A path resolved outside the session's workspace root. See SI-5."""

    http_status = 400


class SandboxError(DevMindError):
    """A sandboxed command could not be started, or was rejected before running."""

    http_status = 500


class SandboxTimeoutError(SandboxError):
    """A sandboxed command exceeded its timeout and was killed."""

    http_status = 504


class LLMProviderError(DevMindError):
    """The LLM provider returned an error or an unusable response."""

    http_status = 502


class PromptError(DevMindError):
    """A prompt file is missing, has malformed frontmatter, declares a name that does
    not match its filename, or its declared `variables` do not match the placeholders
    in its body. A load-time configuration fault.
    """

    http_status = 500


class PromptVariableError(PromptError):
    """`PromptLoader.render()` was given a variable set that does not match the
    prompt's declared `variables` — a missing or an unexpected key. Raised before the
    prompt is sent, so a half-rendered `{placeholder}` can never reach the model.
    """

    http_status = 500


class ToolExecutionError(DevMindError):
    """A tool failed in a way its own `ToolResult(is_error=True)` could not express.

    Ordinary tool failures (bad input, a failing shell command) are returned as an
    `is_error` result, not raised — see the `ToolExecutor` contract in E6. This
    exception is for failures in the executor's own machinery.
    """

    http_status = 500


class InvalidStateTransitionError(DevMindError):
    """A session attempted a transition its state machine does not permit."""

    http_status = 409


class SessionNotFoundError(DevMindError):
    """No session exists with the given id. Introduced in E2 alongside `SessionRepository`."""

    http_status = 404


class RecordNotFoundError(DevMindError):
    """A referenced child row (a todo item, an approval, ...) does not exist.

    Distinct from `SessionNotFoundError`: this is for a lookup *within* a session's
    data (a specific todo item, an approval record), not the session itself.
    """

    http_status = 404


class ApprovalRequiredError(DevMindError):
    """A remote-capable operation was attempted without a persisted APPROVED record.

    Raised by `RemoteOperationGuard.authorize()` (E9) — the layer-3 enforcement of the
    approval gate. See docs/01-solution-design.md §9.
    """

    http_status = 403


class ApprovalAlreadyConsumedError(DevMindError):
    """An approval token was presented a second time. Approval is single-use (SI-4)."""

    http_status = 409


class ApprovalDecisionError(DevMindError):
    """An approval decision was malformed — a rejection with no reason, or a second
    decision on an already-decided session. A decision is final and a human's "no"
    must always carry a why (E9 §"ApprovalService — the gate").
    """

    http_status = 400


class BudgetExceededError(DevMindError):
    """A session crossed its configured cost or step ceiling."""

    http_status = 402


class GitHubError(DevMindError):
    """A `gh` CLI invocation failed."""

    http_status = 502


class RepositoryIngestionError(DevMindError):
    """A repository could not be cloned, profiled, or otherwise ingested."""

    http_status = 422


class PlanningError(DevMindError):
    """`PlannerService` could not produce a usable plan.

    Raised after the one permitted retry: a plan that is still a single vague step,
    empty, or over the item ceiling is a planning failure, and the session fails
    rather than proceeding on a plan that carries no information (E7 §PlannerService).
    """

    http_status = 422
