"""`GitRepositoryCloner` — the git side of ingestion (E4-F2-T1).

A shallow clone at depth 50, then reads of `HEAD` and the default branch. Every
failure becomes a `RepositoryIngestionError` with an actionable message: unreachable
URL, private repo without credentials, empty repo, no default branch. Not an ABC —
one implementation, and the `CommandRunner` it wraps is the seam tests substitute.
"""

from __future__ import annotations

import logging
from pathlib import Path

from devmind.core.constants import (
    GIT_CLONE_DEPTH,
    GIT_CLONE_TIMEOUT_SECONDS,
    NON_INTERACTIVE_GIT_ENV,
)
from devmind.exceptions import RepositoryIngestionError
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput

logger = logging.getLogger(__name__)


class GitRepositoryCloner:
    """Shallow-clones a repo and reads its pinned revision."""

    def __init__(self, runner: CommandRunner, *, depth: int = GIT_CLONE_DEPTH) -> None:
        self._runner = runner
        self._depth = depth

    async def clone(self, repo_url: str, dest: Path) -> None:
        """`git clone --depth <depth> -- <repo_url> <dest>`.

        Raises `RepositoryIngestionError` on any failure, classified from git's stderr.
        """
        result = await self._runner.run(
            ["git", "clone", "--depth", str(self._depth), "--", repo_url, str(dest)],
            env=NON_INTERACTIVE_GIT_ENV,
            timeout=GIT_CLONE_TIMEOUT_SECONDS,
        )
        if not result.ok:
            raise self._classify_clone_failure(repo_url, result)
        logger.info("cloned %s into %s (depth %d)", repo_url, dest, self._depth)

    async def base_commit_sha(self, dest: Path) -> str:
        """`git rev-parse HEAD`. Raises `RepositoryIngestionError` for an empty repo."""
        result = await self._runner.run(
            ["git", "rev-parse", "HEAD"], cwd=dest, env=NON_INTERACTIVE_GIT_ENV
        )
        if not result.ok or not result.stdout.strip():
            raise RepositoryIngestionError(
                "repository has no commits (empty repository)",
                details={"path": str(dest), "stderr": result.stderr.strip()},
            )
        return result.stdout.strip()

    async def default_branch(self, dest: Path) -> str:
        """The branch `origin/HEAD` points at, falling back to the checked-out branch.

        Raises `RepositoryIngestionError` if neither can be determined.
        """
        symref = await self._runner.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=dest,
            env=NON_INTERACTIVE_GIT_ENV,
        )
        if symref.ok and symref.stdout.strip():
            return symref.stdout.strip().removeprefix("origin/")

        current = await self._runner.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=dest, env=NON_INTERACTIVE_GIT_ENV
        )
        branch = current.stdout.strip()
        if current.ok and branch and branch != "HEAD":
            return branch

        raise RepositoryIngestionError(
            "repository has no resolvable default branch",
            details={"path": str(dest)},
        )

    @staticmethod
    def _classify_clone_failure(repo_url: str, result: CommandOutput) -> RepositoryIngestionError:
        text = f"{result.stderr}\n{result.stdout}".lower()
        details = {
            "repo_url": repo_url,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "stderr": result.stderr.strip(),
        }
        if result.timed_out:
            return RepositoryIngestionError(f"cloning {repo_url} timed out", details=details)
        auth_markers = ("authentication failed", "/bin/false", "terminal prompts disabled")
        if any(marker in text for marker in auth_markers):
            return RepositoryIngestionError(
                f"repository {repo_url} is private and no credentials are available",
                details=details,
            )
        if "repository not found" in text or "not found" in text:
            return RepositoryIngestionError(
                f"repository {repo_url} was not found (or is private and needs credentials)",
                details=details,
            )
        if (
            "could not resolve host" in text
            or "could not read from remote" in text
            or "unable to access" in text
            or "connection refused" in text
            or "network is unreachable" in text
        ):
            return RepositoryIngestionError(
                f"repository URL {repo_url} is unreachable", details=details
            )
        first_line = result.stderr.strip().splitlines()[0] if result.stderr.strip() else ""
        return RepositoryIngestionError(
            f"git clone of {repo_url} failed: {first_line or f'exit {result.exit_code}'}",
            details=details,
        )
