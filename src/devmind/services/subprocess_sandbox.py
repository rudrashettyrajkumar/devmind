"""`SubprocessSandbox` — the default developer-machine backend (E5-F2-T1).

**Honest limitation.** This is process isolation, not a security boundary: repo code
can still read the host filesystem and open sockets. It is the correct choice for a
trusted repo on a developer machine (the primary dev box here has no Docker) and the
wrong one for an untrusted repo. `SandboxFactory` logs a warning naming this at
startup, the README documents it, and the resolved backend is persisted on the
session record so any run's isolation level is knowable after the fact.

What it *does* enforce: argv-only execution (never a shell), the binary allowlist
(SI-8), a scrubbed credential-free environment (SI-2, best effort), a hard per-command
timeout, and a process-group SIGKILL on timeout so a test runner that forked children
cannot orphan them onto the workspace.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from pathlib import Path

from devmind.core.constants import (
    DEPENDENCY_INSTALL_TIMEOUT_SECONDS,
    DURATION_PRECISION_DIGITS,
    SANDBOX_KILL_GRACE_SECONDS,
)
from devmind.exceptions import SandboxError
from devmind.interfaces.sandbox import Sandbox
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import CommandResult, SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.output_truncator import OutputTruncator
from devmind.services.sandbox_environment import SandboxEnvironment
from devmind.services.workspace_path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)


class SubprocessSandbox(Sandbox):
    """Runs repo commands as host subprocesses in their own session group."""

    def __init__(
        self,
        allowlist: CommandAllowlist,
        truncator: OutputTruncator,
        environment: SandboxEnvironment | None = None,
    ) -> None:
        self._allowlist = allowlist
        self._truncator = truncator
        self._environment = environment or SandboxEnvironment()
        self._guard: WorkspacePathGuard | None = None

    async def setup(self, workspace: Path) -> None:
        self._guard = WorkspacePathGuard(workspace)
        logger.info("subprocess sandbox ready at %s", self._guard.root)

    async def teardown(self) -> None:
        self._guard = None

    async def install_dependencies(self, profile: RepoProfile) -> CommandResult:
        if not profile.install_command:
            return CommandResult(
                argv=(),
                exit_code=0,
                stdout="no install command for this repository",
                stderr="",
                duration_seconds=0.0,
            )
        return await self.run(
            SandboxCommand(
                argv=profile.install_command,
                timeout_seconds=DEPENDENCY_INSTALL_TIMEOUT_SECONDS,
            )
        )

    async def run(self, command: SandboxCommand) -> CommandResult:
        if self._guard is None:
            raise SandboxError("sandbox.run() called before setup()")
        self._allowlist.validate(command.argv)
        cwd = self._resolve_cwd(command.cwd)
        env = self._environment.build(command.env)

        start = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:  # FileNotFoundError / PermissionError / … all subclass this
            raise SandboxError(
                f"could not start {command.argv[0]!r}: {exc}",
                details={"argv": list(command.argv)},
            ) from exc

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=command.timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            await self._kill_group(process)
            stdout_bytes, stderr_bytes = await self._drain(process)

        duration = time.monotonic() - start
        stdout, out_trunc = self._truncator.truncate_bytes(stdout_bytes)
        stderr, err_trunc = self._truncator.truncate_bytes(stderr_bytes)
        return CommandResult(
            argv=command.argv,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, DURATION_PRECISION_DIGITS),
            timed_out=timed_out,
            truncated=out_trunc or err_trunc,
        )

    def _resolve_cwd(self, cwd: str | None) -> Path:
        assert self._guard is not None  # guarded by run()
        if cwd is None:
            return self._guard.root
        return self._guard.resolve(cwd)

    @staticmethod
    async def _kill_group(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError):
                process.kill()

    @staticmethod
    async def _drain(process: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
        try:
            return await asyncio.wait_for(process.communicate(), timeout=SANDBOX_KILL_GRACE_SECONDS)
        except TimeoutError:
            return b"", b""
