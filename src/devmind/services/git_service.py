"""`GitService` — the write-phase git operations (E10-F1-T1).

Branch, stage, commit, push. `push()` is the first remote-capable method in the
codebase: it is called only from `PRService`, only after
`RemoteOperationGuard.authorize()` has returned. There is no force-push anywhere in
this class, no path that writes a default branch, and no branch delete — and a
failed push is never retried (spec §"Failure handling").

Every invocation goes through the injected `CommandRunner` (host `git`, argv-only,
never a shell), the same seam `GitRepositoryCloner` uses for the read phase. Not an
ABC — one implementation, and the runner is what tests substitute (Claude.md §9).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from devmind.core.config import Settings
from devmind.core.constants import (
    AGENT_GIT_AUTHOR_EMAIL,
    AGENT_GIT_AUTHOR_NAME,
    GIT_PUSH_TIMEOUT_SECONDS,
    GIT_WRITE_OP_TIMEOUT_SECONDS,
    NON_INTERACTIVE_GIT_ENV,
)
from devmind.core.enums import GitFailureReason
from devmind.exceptions import GitDeliveryError
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput
from devmind.schemas.pull_request import CommitMessage
from devmind.services.workspace_path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)

_DRY_RUN_SHA: Final[str] = "0" * 40

# git identity + non-interactive env forced onto every write-phase invocation.
_AUTHOR_ENV: Final[Mapping[str, str]] = {
    "GIT_AUTHOR_NAME": AGENT_GIT_AUTHOR_NAME,
    "GIT_AUTHOR_EMAIL": AGENT_GIT_AUTHOR_EMAIL,
    "GIT_COMMITTER_NAME": AGENT_GIT_AUTHOR_NAME,
    "GIT_COMMITTER_EMAIL": AGENT_GIT_AUTHOR_EMAIL,
    **NON_INTERACTIVE_GIT_ENV,
}


class GitService:
    """Runs branch / stage / commit / push for one workspace."""

    def __init__(
        self, runner: CommandRunner, guard: WorkspacePathGuard, settings: Settings
    ) -> None:
        # `guard` is held for symmetry with the other path-taking services (see
        # `DiffService`); the workspace is validated against its root on every call.
        self._runner = runner
        self._guard = guard
        self._settings = settings

    async def create_branch(self, workspace: Path, name: str) -> str:
        """`git switch -c <name>`. Returns `name`. Raises `GitDeliveryError` on failure."""
        self._check_workspace(workspace)
        if self._settings.dry_run:
            self._log_dry_run(["git", "switch", "-c", name], workspace)
            return name
        result = await self._run(["git", "switch", "-c", name], workspace)
        if not result.ok:
            raise self._failure(
                f"could not create branch {name!r}",
                GitFailureReason.BRANCH_CREATE_FAILED,
                result,
            )
        return name

    async def stage_all(self, workspace: Path) -> None:
        """`git add -A` — stage every change in the working tree."""
        self._check_workspace(workspace)
        if self._settings.dry_run:
            self._log_dry_run(["git", "add", "-A"], workspace)
            return
        result = await self._run(["git", "add", "-A"], workspace)
        if not result.ok:
            raise self._failure(
                "could not stage the working tree",
                GitFailureReason.COMMIT_FAILED,
                result,
            )

    async def commit(self, workspace: Path, message: CommitMessage) -> str:
        """`git commit -m <rendered>` then `git rev-parse HEAD`. Returns the new sha."""
        self._check_workspace(workspace)
        rendered = message.render()
        if self._settings.dry_run:
            self._log_dry_run(["git", "commit", "-m", "<commit message>"], workspace)
            return _DRY_RUN_SHA
        committed = await self._run(["git", "commit", "-m", rendered], workspace)
        if not committed.ok:
            raise self._failure("git commit failed", GitFailureReason.COMMIT_FAILED, committed)
        head = await self._run(["git", "rev-parse", "HEAD"], workspace)
        if not head.ok or not head.stdout.strip():
            raise self._failure(
                "could not read HEAD after the commit",
                GitFailureReason.COMMIT_FAILED,
                head,
            )
        return head.stdout.strip()

    async def push(self, workspace: Path, branch: str) -> None:
        """`git push --set-upstream origin <branch>`. **GATED** — see the module docstring.

        Never a force-push. A rejected push raises `GitDeliveryError` with a specific
        `GitFailureReason` and is never retried.
        """
        self._check_workspace(workspace)
        argv = ["git", "push", "--set-upstream", "origin", branch]
        if self._settings.dry_run:
            self._log_dry_run(argv, workspace)
            return
        result = await self._runner.run(
            argv, cwd=workspace, env=_AUTHOR_ENV, timeout=GIT_PUSH_TIMEOUT_SECONDS
        )
        if not result.ok:
            raise self._classify_push_failure(branch, result)
        logger.info("pushed branch %s to origin", branch)

    async def list_remote_branches(self, workspace: Path) -> frozenset[str]:
        """`git ls-remote --heads origin` → the set of existing branch names.

        Best-effort input to `BranchNamer` collision avoidance: on any failure
        (offline, no such remote) this returns an empty set and logs, so naming
        falls back to the un-suffixed name and a genuine collision is still caught
        by `push()` as `REMOTE_BRANCH_EXISTS`. A read, not a write — no `_AUTHOR_ENV`.
        """
        self._check_workspace(workspace)
        if self._settings.dry_run:
            return frozenset()
        result = await self._runner.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=workspace,
            env=NON_INTERACTIVE_GIT_ENV,
            timeout=GIT_WRITE_OP_TIMEOUT_SECONDS,
        )
        if not result.ok:
            logger.warning(
                "could not list remote branches (%s) — branch-name collision avoidance "
                "will rely on the push instead",
                result.stderr.strip() or f"exit {result.exit_code}",
            )
            return frozenset()
        names: set[str] = set()
        for line in result.stdout.splitlines():
            _, _, ref = line.partition("\t")
            ref = ref.strip()
            if ref.startswith("refs/heads/"):
                names.add(ref.removeprefix("refs/heads/"))
        return frozenset(names)

    # --- internals ---------------------------------------------------------

    async def _run(self, argv: list[str], workspace: Path) -> CommandOutput:
        return await self._runner.run(
            argv, cwd=workspace, env=_AUTHOR_ENV, timeout=GIT_WRITE_OP_TIMEOUT_SECONDS
        )

    def _check_workspace(self, workspace: Path) -> None:
        if workspace.resolve() != self._guard.root:
            raise GitDeliveryError(
                f"workspace {workspace} is not this service's guarded root",
                details={"workspace": str(workspace), "root": str(self._guard.root)},
            )

    @staticmethod
    def _log_dry_run(argv: list[str], workspace: Path) -> None:
        logger.info("dry-run: would run %s (cwd=%s)", argv, workspace)

    @staticmethod
    def _failure(prefix: str, reason: GitFailureReason, result: CommandOutput) -> GitDeliveryError:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
        return GitDeliveryError(
            f"{prefix}: {detail}",
            reason=reason,
            details={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "stderr": result.stderr.strip(),
            },
        )

    @staticmethod
    def _classify_push_failure(branch: str, result: CommandOutput) -> GitDeliveryError:
        text = f"{result.stderr}\n{result.stdout}".lower()
        details: dict[str, object] = {
            "branch": branch,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "stderr": result.stderr.strip(),
        }
        if "non-fast-forward" in text or "fetch first" in text or "[rejected]" in text:
            return GitDeliveryError(
                f"push of {branch!r} was rejected as non-fast-forward — the branch is "
                "retained locally; resolve it by hand, nothing is retried automatically",
                reason=GitFailureReason.PUSH_REJECTED,
                details=details,
            )
        if (
            "permission" in text
            or "403" in text
            or "not authorized" in text
            or "access denied" in text
            or "could not read from remote" in text
        ):
            return GitDeliveryError(
                f"push of {branch!r} was denied — the credential in use lacks push "
                "scope on this repository (needs `repo` / `contents:write`)",
                reason=GitFailureReason.NO_PUSH_PERMISSION,
                details=details,
            )
        if "already exists" in text or "cannot lock ref" in text:
            return GitDeliveryError(
                f"a branch named {branch!r} already exists on the remote — it will not "
                "be overwritten",
                reason=GitFailureReason.REMOTE_BRANCH_EXISTS,
                details=details,
            )
        first_line = result.stderr.strip().splitlines()[0] if result.stderr.strip() else ""
        return GitDeliveryError(
            f"push of {branch!r} failed: {first_line or f'exit {result.exit_code}'}",
            reason=GitFailureReason.PUSH_REJECTED,
            details=details,
        )
