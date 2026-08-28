"""Best-effort sandbox backend resolution for startup and `/health`.

This is a minimal placeholder ahead of E5's `SandboxFactory`, which will own the real
Docker-SDK liveness probe and construct the actual `Sandbox` implementations
(`docs/specs/epic-05-sandbox-execution.md`, E5-F2-T3). E1 only needs enough to resolve
`SandboxBackend.AUTO` to a concrete backend at startup — so the default developer
experience, no Docker required, works from the very first commit — and to report that
resolution on `/health`. `SandboxFactory` supersedes this class; it is not meant to
grow further.
"""

import logging
import shutil
import subprocess

from devmind.core.constants import DOCKER_PROBE_TIMEOUT_SECONDS
from devmind.core.enums import SandboxBackend

logger = logging.getLogger(__name__)


class SandboxBackendProbe:
    """Resolves `SandboxBackend.AUTO` to a concrete backend, once, at startup."""

    def resolve(self, configured: SandboxBackend) -> SandboxBackend:
        if configured is not SandboxBackend.AUTO:
            logger.info("sandbox backend explicitly configured: %s", configured.value)
            return configured

        if self._docker_available():
            logger.info("sandbox backend resolved: docker")
            return SandboxBackend.DOCKER

        logger.warning(
            "Docker unavailable — falling back to SandboxBackend.SUBPROCESS. This is "
            "process isolation only, not a security boundary. See "
            "docs/01-solution-design.md section 7."
        )
        return SandboxBackend.SUBPROCESS

    def _docker_available(self) -> bool:
        if shutil.which("docker") is None:
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=DOCKER_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
