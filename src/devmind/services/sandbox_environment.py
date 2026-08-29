"""`SandboxEnvironment` — builds the scrubbed environment a sandbox command runs with.

SI-2: repo code must never inherit the operator's credentials. The environment is
built from an explicit allowlist of host variables (`PATH`, `HOME`, `LANG`, …), then
the forced overrides are applied (blanking `GH_TOKEN` / `GITHUB_TOKEN` /
`ANTHROPIC_API_KEY`, disabling interactive git), then the caller's per-command `env`.
Nothing else from `os.environ` gets through.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from devmind.core.constants import SANDBOX_ENV_ALLOWLIST, SANDBOX_ENV_OVERRIDES


class SandboxEnvironment:
    """Constructs the minimal, credential-free environment for a sandboxed process."""

    def __init__(
        self,
        allowlist: frozenset[str] = SANDBOX_ENV_ALLOWLIST,
        overrides: Mapping[str, str] = SANDBOX_ENV_OVERRIDES,
    ) -> None:
        self._allowlist = allowlist
        self._overrides = dict(overrides)

    def build(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Allowlisted host vars, then forced overrides, then `extra` (lowest trust,
        applied last but still unable to un-blank a scrubbed credential — the
        overrides win for any key they name).
        """
        env: dict[str, str] = {
            name: value for name, value in os.environ.items() if name in self._allowlist
        }
        if extra:
            env.update({key: value for key, value in extra.items() if key not in self._overrides})
        env.update(self._overrides)
        return env
