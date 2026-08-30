"""DTOs for the sandbox execution layer (E5).

`SandboxCommand` is argv-only by construction — there is no field that could carry a
shell string, because nothing in this codebase runs through a shell (SI-8). Every
sandbox backend returns the same `CommandResult`.
"""

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.constants import SANDBOX_COMMAND_TIMEOUT_SECONDS


class SandboxCommand(BaseModel):
    """One command to run inside a sandbox.

    `cwd`, when given, is a workspace-relative path resolved through
    `WorkspacePathGuard` before execution — an escape raises `PathEscapeError`.
    `env` entries are overlaid on the sandbox's scrubbed base environment; they
    cannot re-introduce a host credential the scrub removed.
    """

    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str | None = None
    timeout_seconds: int = Field(default=SANDBOX_COMMAND_TIMEOUT_SECONDS, gt=0)
    env: dict[str, str] = Field(default_factory=dict)


class CommandResult(BaseModel):
    """The captured outcome of one sandboxed command — identical shape from every
    backend, so the contract test suite and every caller are backend-agnostic.
    """

    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False

    @property
    def succeeded(self) -> bool:
        """True only for a clean exit — code 0 and no timeout."""
        return self.exit_code == 0 and not self.timed_out
