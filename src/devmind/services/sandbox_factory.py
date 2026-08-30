"""`SandboxFactory` — resolves the backend once and builds the `Sandbox` (E5-F2-T3).

`AUTO` probes the Docker daemon (`client.ping()`, short timeout): reachable → `DOCKER`,
otherwise `SUBPROCESS` with a logged warning. An explicit `DOCKER` that is unavailable
is a `ConfigurationError`, **not** a silent downgrade — an operator who asked for
kernel isolation must not get process isolation without being told.

The resolved backend is logged once and written to `SessionModel.sandbox_backend` by
the caller, so any run's isolation level is knowable after the fact. This class
supersedes the E1 `SandboxBackendProbe` placeholder.
"""

from __future__ import annotations

import logging

import docker
from docker.errors import DockerException

from devmind.core.config import Settings
from devmind.core.constants import DOCKER_PROBE_TIMEOUT_SECONDS, MAX_TEST_OUTPUT_CHARS
from devmind.core.enums import SandboxBackend
from devmind.exceptions import ConfigurationError
from devmind.interfaces.sandbox import Sandbox
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.docker_sandbox import DockerSandbox
from devmind.services.output_truncator import OutputTruncator
from devmind.services.subprocess_sandbox import SubprocessSandbox

logger = logging.getLogger(__name__)

_SUBPROCESS_LIMITATION = (
    "sandbox backend is SUBPROCESS: process isolation only, NOT a security boundary — "
    "repo code can read the host filesystem and open sockets. Correct for a trusted "
    "repo on a dev box, wrong for an untrusted one. See docs/01-solution-design.md §7."
)


class SandboxFactory:
    """Backend resolution and `Sandbox` construction from settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve_backend(self) -> SandboxBackend:
        configured = self._settings.sandbox_backend
        if configured is SandboxBackend.SUBPROCESS:
            return SandboxBackend.SUBPROCESS
        if configured is SandboxBackend.DOCKER:
            if not self._docker_reachable():
                raise ConfigurationError(
                    "SANDBOX_BACKEND=docker but the Docker daemon is not reachable — "
                    "refusing to downgrade to subprocess isolation silently"
                )
            return SandboxBackend.DOCKER
        # AUTO
        if self._docker_reachable():
            logger.info("sandbox backend resolved: docker")
            return SandboxBackend.DOCKER
        logger.warning("Docker unavailable — %s", _SUBPROCESS_LIMITATION)
        return SandboxBackend.SUBPROCESS

    def create(self) -> Sandbox:
        backend = self.resolve_backend()
        allowlist = CommandAllowlist()
        truncator = OutputTruncator(MAX_TEST_OUTPUT_CHARS)
        if backend is SandboxBackend.DOCKER:
            return DockerSandbox(
                client=docker.from_env(timeout=DOCKER_PROBE_TIMEOUT_SECONDS),
                image=self._settings.sandbox_image,
                allowlist=allowlist,
                truncator=truncator,
            )
        logger.warning(_SUBPROCESS_LIMITATION)
        return SubprocessSandbox(allowlist=allowlist, truncator=truncator)

    @staticmethod
    def _docker_reachable() -> bool:
        try:
            client = docker.from_env(timeout=DOCKER_PROBE_TIMEOUT_SECONDS)
            return bool(client.ping())
        except (DockerException, OSError):
            return False
