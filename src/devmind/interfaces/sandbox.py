"""The seam for running the target repository's own commands (E5).

A justified ABC (Claude.md §4): two implementations ship in v1 — `DockerSandbox`
(kernel-enforced network isolation) and `SubprocessSandbox` (process isolation for a
trusted dev box) — plus `FakeSandbox` in tests. Three implementations, one contract.

Lifecycle: `setup(workspace)` once, any number of `run(command)` / `install_dependencies`
calls, then `teardown()` exactly once — including on the failure path, so a crashed
run never leaks a container.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import CommandResult, SandboxCommand


class Sandbox(ABC):
    """Run repo commands without letting them reach the network or the host."""

    @abstractmethod
    async def setup(self, workspace: Path) -> None:
        """Prepare the sandbox to execute commands against `workspace`."""
        ...

    @abstractmethod
    async def run(self, command: SandboxCommand) -> CommandResult:
        """Execute one command. A non-zero exit or a timeout is returned on the
        `CommandResult`, never raised; a disallowed binary or a `cwd` escape raises.
        """
        ...

    @abstractmethod
    async def install_dependencies(self, profile: RepoProfile) -> CommandResult:
        """Run `profile.install_command` with the longer dependency-install timeout.

        A no-op success when the profile has no install command. Under Docker this is
        the one step allowed network access (see `DockerSandbox`); everything else
        runs with none.
        """
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """Release everything `setup()` acquired. Safe to call after a failed setup."""
        ...
