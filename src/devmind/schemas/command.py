"""DTO for the host command-execution seam (E4).

`CommandRunner` runs `git` and `gh` on the host during the read-only ingestion phase.
Its single return type is `CommandOutput` — callers branch on `.ok`, never on a raw
exit code or a stderr string match.
"""

from pydantic import BaseModel, ConfigDict


class CommandOutput(BaseModel):
    """The captured result of one host command invocation.

    A non-zero exit or a timeout is data, not an exception: the runner always returns
    this, and the caller decides whether that outcome is a failure in its context.
    """

    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """True only for a clean exit — code 0 and no timeout."""
        return self.exit_code == 0 and not self.timed_out
