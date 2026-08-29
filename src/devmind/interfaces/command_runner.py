"""The seam for running a trusted binary on the host (E4).

Used by `GitHubClient`, `GitRepositoryCloner`, and `CodeSearchService` to invoke
`gh`, `git`, and `rg`/`grep` during the read-only ingestion phase. This is NOT the
sandbox — E5 owns running the *target repo's* commands. Host execution here is
argv-only (never `shell=True`) and time-bounded.

An ABC because tests must substitute it: `GitHubClient` and the ingestion service are
covered with a `FakeCommandRunner` so the suite never shells out to a real `gh` or
touches the network (Claude.md §4 — a real determinism boundary).
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path

from devmind.schemas.command import CommandOutput


class CommandRunner(ABC):
    """Run one command, capture its output, return it. Never raises on a non-zero
    exit or a timeout — those are reported on the `CommandOutput`.
    """

    @abstractmethod
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandOutput:
        """Execute `argv` (never through a shell).

        `env` entries are overlaid on the runner's own scrubbed base environment.
        `timeout` falls back to the runner's default; on expiry the process group is
        killed and `CommandOutput.timed_out` is `True`. A non-zero exit or a missing
        binary is returned on the `CommandOutput`, never raised; an empty `argv` is a
        caller-contract violation and raises `ValueError`.
        """
        ...
