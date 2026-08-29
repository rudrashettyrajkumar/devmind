"""`DockerSandbox` — kernel-enforced isolation for the target repo's commands (E5-F2-T2).

One container per session, created in `setup()` and removed with `force=True` in
`teardown()` (including on the failure path, so a crashed run never leaks a
container). The container runs `network_mode="none"` — **SI-2 is enforced by the
kernel here**, not by asking anything nicely — with the workspace bind-mounted at
`/workspace`, a non-root user, all capabilities dropped, `no-new-privileges`, and
memory / CPU / pid caps.

**Network during dependency install.** `network_mode="none"` cannot be toggled on a
running container, so `install_dependencies()` runs `profile.install_command` in a
*separate, throwaway, networked* container that shares the same workspace bind mount —
packages land in `.venv/` inside the workspace and persist into the no-network
session container. Every other command runs with no network at all.

All blocking Docker SDK calls go through `asyncio.to_thread` so they never stall the
event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from docker import DockerClient  # resolves to Any under mypy's ignore_missing_imports
from docker.errors import DockerException
from docker.models.containers import Container

from devmind.core.constants import (
    DEPENDENCY_INSTALL_TIMEOUT_SECONDS,
    DOCKER_CAP_DROP,
    DOCKER_CONTAINER_USER,
    DOCKER_IDLE_COMMAND,
    DOCKER_MEM_LIMIT,
    DOCKER_NANO_CPUS,
    DOCKER_NETWORK_INSTALL,
    DOCKER_NETWORK_ISOLATED,
    DOCKER_PIDS_LIMIT,
    DOCKER_SECURITY_OPT,
    DOCKER_WORKSPACE_MOUNT,
    DOCKER_WORKSPACE_MOUNT_MODE,
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


class DockerSandbox(Sandbox):
    """Runs repo commands inside a locked-down, network-less container."""

    def __init__(
        self,
        client: DockerClient,
        image: str,
        allowlist: CommandAllowlist,
        truncator: OutputTruncator,
        environment: SandboxEnvironment | None = None,
    ) -> None:
        self._client = client
        self._image = image
        self._allowlist = allowlist
        self._truncator = truncator
        self._environment = environment or SandboxEnvironment()
        self._guard: WorkspacePathGuard | None = None
        self._workspace: Path | None = None
        self._container: Container | None = None

    async def setup(self, workspace: Path) -> None:
        self._guard = WorkspacePathGuard(workspace)
        self._workspace = self._guard.root
        container = await asyncio.to_thread(self._create_container)
        await asyncio.to_thread(container.start)
        self._container = container
        logger.info("docker sandbox container %s started (network=none)", container.short_id)

    async def teardown(self) -> None:
        container = self._container
        self._container = None
        self._guard = None
        if container is not None:
            try:
                await asyncio.to_thread(container.remove, force=True)
            except DockerException as exc:
                # teardown must never raise — a leaked container is a logged warning,
                # not a crashed session.
                logger.warning("could not remove sandbox container: %s", exc)

    async def install_dependencies(self, profile: RepoProfile) -> CommandResult:
        if not profile.install_command:
            return CommandResult(
                argv=(),
                exit_code=0,
                stdout="no install command for this repository",
                stderr="",
                duration_seconds=0.0,
            )
        self._allowlist.validate(profile.install_command)
        return await self._run_in_throwaway_container(
            SandboxCommand(
                argv=profile.install_command,
                timeout_seconds=DEPENDENCY_INSTALL_TIMEOUT_SECONDS,
            )
        )

    async def run(self, command: SandboxCommand) -> CommandResult:
        if self._container is None or self._guard is None:
            raise SandboxError("sandbox.run() called before setup()")
        self._allowlist.validate(command.argv)
        workdir = self._container_workdir(command.cwd)
        env = self._environment.build(command.env)

        start = time.monotonic()
        try:
            exit_code, stdout_b, stderr_b = await asyncio.wait_for(
                asyncio.to_thread(self._exec, list(command.argv), workdir, env),
                timeout=command.timeout_seconds,
            )
            timed_out = False
        except TimeoutError:
            timed_out = True
            exit_code, stdout_b, stderr_b = -1, b"", b""
            await self._recover_after_timeout()

        stdout, out_trunc = self._truncator.truncate_bytes(stdout_b)
        stderr, err_trunc = self._truncator.truncate_bytes(stderr_b)
        return CommandResult(
            argv=command.argv,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(time.monotonic() - start, DURATION_PRECISION_DIGITS),
            timed_out=timed_out,
            truncated=out_trunc or err_trunc,
        )

    # --- Docker plumbing -------------------------------------------------------

    def _container_kwargs(self, *, network: str) -> dict[str, object]:
        assert self._workspace is not None
        return {
            "network_mode": network,
            "working_dir": DOCKER_WORKSPACE_MOUNT,
            "volumes": {
                str(self._workspace): {
                    "bind": DOCKER_WORKSPACE_MOUNT,
                    "mode": DOCKER_WORKSPACE_MOUNT_MODE,
                }
            },
            "mem_limit": DOCKER_MEM_LIMIT,
            "nano_cpus": DOCKER_NANO_CPUS,
            "pids_limit": DOCKER_PIDS_LIMIT,
            "user": DOCKER_CONTAINER_USER,
            "cap_drop": list(DOCKER_CAP_DROP),
            "security_opt": list(DOCKER_SECURITY_OPT),
            "detach": True,
        }

    def _create_container(self) -> Container:
        return self._client.containers.create(
            self._image,
            command=list(DOCKER_IDLE_COMMAND),
            **self._container_kwargs(network=DOCKER_NETWORK_ISOLATED),
        )

    def _exec(self, argv: list[str], workdir: str, env: dict[str, str]) -> tuple[int, bytes, bytes]:
        assert self._container is not None
        result = self._container.exec_run(
            cmd=argv,
            workdir=workdir,
            environment=env,
            demux=True,
            user=DOCKER_CONTAINER_USER,
        )
        stdout_b, stderr_b = result.output if result.output is not None else (None, None)
        return result.exit_code or 0, stdout_b or b"", stderr_b or b""

    async def _run_in_throwaway_container(self, command: SandboxCommand) -> CommandResult:
        env = self._environment.build(command.env)
        start = time.monotonic()

        def _run() -> tuple[int, bytes]:
            container = self._client.containers.run(
                self._image,
                command=list(command.argv),
                environment=env,
                **self._container_kwargs(network=DOCKER_NETWORK_INSTALL),
            )
            try:
                outcome = container.wait(timeout=command.timeout_seconds)
                logs: bytes = container.logs(stdout=True, stderr=True)
                return int(outcome.get("StatusCode", -1)), logs
            finally:
                container.remove(force=True)

        try:
            exit_code, logs = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=command.timeout_seconds + SANDBOX_KILL_GRACE_SECONDS,
            )
            timed_out = False
        except TimeoutError:
            exit_code, logs, timed_out = -1, b"", True

        text, truncated = self._truncator.truncate_bytes(logs)
        return CommandResult(
            argv=command.argv,
            exit_code=exit_code,
            stdout=text,
            stderr="",
            duration_seconds=round(time.monotonic() - start, DURATION_PRECISION_DIGITS),
            timed_out=timed_out,
            truncated=truncated,
        )

    async def _recover_after_timeout(self) -> None:
        """A timed-out `exec_run` leaves its process alive in the container; kill the
        container and stand a fresh one up so subsequent `run()`s still work. The
        workspace (and any installed `.venv`) is a bind mount, so it survives.
        """
        old = self._container
        self._container = None
        if old is not None:
            try:
                await asyncio.to_thread(old.remove, force=True)
            except DockerException as exc:
                logger.warning("could not remove timed-out container: %s", exc)
        container = await asyncio.to_thread(self._create_container)
        await asyncio.to_thread(container.start)
        self._container = container

    def _container_workdir(self, cwd: str | None) -> str:
        assert self._guard is not None
        if cwd is None:
            return DOCKER_WORKSPACE_MOUNT
        relative = self._guard.resolve(cwd).relative_to(self._guard.root)
        if not relative.parts:
            return DOCKER_WORKSPACE_MOUNT
        return f"{DOCKER_WORKSPACE_MOUNT}/{relative.as_posix()}"
