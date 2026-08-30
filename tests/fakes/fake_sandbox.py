"""A `Sandbox` that returns scripted `CommandResult`s and records every call.

Lets service-layer tests drive commands deterministically without spawning a real
process or a container (devmind-testing: fake-based determinism).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from devmind.interfaces.sandbox import Sandbox
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import CommandResult, SandboxCommand


def command_result(
    argv: tuple[str, ...] = ("echo", "ok"),
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    duration_seconds: float = 0.01,
    timed_out: bool = False,
    truncated: bool = False,
) -> CommandResult:
    return CommandResult(
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration_seconds,
        timed_out=timed_out,
        truncated=truncated,
    )


class FakeSandbox(Sandbox):
    """Scripted results in FIFO order, with a default for anything past the script."""

    def __init__(
        self,
        results: list[CommandResult] | None = None,
        *,
        default: CommandResult | None = None,
    ) -> None:
        self._results: deque[CommandResult] = deque(results or [])
        self._default = default or command_result()
        self.commands: list[SandboxCommand] = []
        self.workspace: Path | None = None
        self.setup_calls = 0
        self.teardown_calls = 0
        self.install_calls = 0

    def queue(self, *results: CommandResult) -> None:
        """Append scripted results a later `run()` will return in order."""
        self._results.extend(results)

    async def setup(self, workspace: Path) -> None:
        self.setup_calls += 1
        self.workspace = workspace

    async def run(self, command: SandboxCommand) -> CommandResult:
        self.commands.append(command)
        result = self._results.popleft() if self._results else self._default
        return result.model_copy(update={"argv": command.argv})

    async def install_dependencies(self, profile: RepoProfile) -> CommandResult:
        self.install_calls += 1
        if self._results:
            return self._results.popleft()
        return command_result(argv=profile.install_command or ())

    async def teardown(self) -> None:
        self.teardown_calls += 1
