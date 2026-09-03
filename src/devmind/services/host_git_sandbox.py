"""`HostGitSandbox` — a read-only `Sandbox` adapter that runs `git` on the host (E11).

`DiffService` (E9) reads the working-tree diff through the `Sandbox` seam. During a
run that seam is a real isolated sandbox; *after* the run — when `GET /sessions/{id}/
approval-request` or `PRService` needs the same diff and the run's sandbox is long
gone — this adapter stands in. It only ever runs `git` in one fixed workspace via the
host `CommandRunner`, never installs anything, and has nothing to tear down.

It is deliberately not a general sandbox: `setup` / `install_dependencies` / `teardown`
are no-ops, and `run` refuses any argv whose first element is not `git`. The isolation
guarantees the real sandbox provides do not apply here, which is fine — the only
callers are read-only diff reads against a workspace DevMind already owns.
"""

from __future__ import annotations

import time
from pathlib import Path

from devmind.core.constants import DIFF_ENDPOINT_TIMEOUT_SECONDS, NON_INTERACTIVE_GIT_ENV
from devmind.exceptions import SandboxError
from devmind.interfaces.command_runner import CommandRunner
from devmind.interfaces.sandbox import Sandbox
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import CommandResult, SandboxCommand


class HostGitSandbox(Sandbox):
    """Runs `git` in one workspace on the host. Read-only by construction."""

    def __init__(self, workspace: Path, runner: CommandRunner) -> None:
        self._workspace = workspace
        self._runner = runner

    async def setup(self, workspace: Path) -> None:
        return None

    async def install_dependencies(self, profile: RepoProfile) -> CommandResult:
        return CommandResult(
            argv=("noop",), exit_code=0, stdout="", stderr="", duration_seconds=0.0
        )

    async def teardown(self) -> None:
        return None

    async def run(self, command: SandboxCommand) -> CommandResult:
        if not command.argv or command.argv[0] != "git":
            got = command.argv[0] if command.argv else "<empty>"
            raise SandboxError(
                f"HostGitSandbox only runs git, got {got!r}",
                details={"argv": list(command.argv)},
            )
        started = time.monotonic()
        output = await self._runner.run(
            ["git", "-C", str(self._workspace), *command.argv[1:]],
            env=NON_INTERACTIVE_GIT_ENV,
            timeout=float(command.timeout_seconds or DIFF_ENDPOINT_TIMEOUT_SECONDS),
        )
        return CommandResult(
            argv=tuple(output.argv),
            exit_code=output.exit_code,
            stdout=output.stdout,
            stderr=output.stderr,
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=output.timed_out,
        )
