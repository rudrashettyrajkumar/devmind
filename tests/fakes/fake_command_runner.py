"""A `CommandRunner` that returns scripted `CommandOutput`s and records every call.

Keeps the test suite from ever shelling out to a real `gh`, `git`, or `rg` — and
from ever touching the network (devmind-testing ground rule 1).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path

from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput


def command_output(
    argv: Sequence[str],
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
) -> CommandOutput:
    """Terse constructor for a scripted result."""
    return CommandOutput(
        argv=tuple(argv),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


class RecordedCall:
    """One invocation the fake saw."""

    def __init__(
        self,
        argv: list[str],
        cwd: Path | None,
        env: dict[str, str],
        timeout: float | None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.timeout = timeout


class FakeCommandRunner(CommandRunner):
    """Matches by argv prefix first, then falls back to a FIFO queue, then a default."""

    def __init__(
        self,
        queue: list[CommandOutput] | None = None,
        *,
        by_prefix: dict[tuple[str, ...], CommandOutput] | None = None,
        default: CommandOutput | None = None,
    ) -> None:
        self.calls: list[RecordedCall] = []
        self._queue: deque[CommandOutput] = deque(queue or [])
        self._by_prefix = by_prefix or {}
        self._default = default

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandOutput:
        args = list(argv)
        self.calls.append(RecordedCall(args, cwd, dict(env or {}), timeout))

        for prefix, output in self._by_prefix.items():
            if tuple(args[: len(prefix)]) == prefix:
                return output
        if self._queue:
            return self._queue.popleft()
        if self._default is not None:
            return self._default
        raise AssertionError(f"FakeCommandRunner has no scripted output for {args}")
