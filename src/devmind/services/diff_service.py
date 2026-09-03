"""`DiffService` — the final change, as a reviewer needs to see it (E9-F1-T2).

Three questions the approval payload asks of the working tree:

* what changed, as one unified diff (`unified_diff`);
* how much changed, per file (`file_stats`);
* did the agent only touch tests (`touches_only_tests`) — a diff that moves the
  goalposts instead of fixing the bug, which the payload must warn about.

Everything runs `git` **inside the sandbox** (no host `git` call, no network) and the
diff is capped at `MAX_DIFF_CHARS` with an explicit marker: a truncated diff is never
handed to a human as if it were the whole change.

Nothing is committed before the approval gate, so the working-tree diff (`git diff`)
*is* the diff against the base commit.
"""

from __future__ import annotations

from pathlib import Path

from devmind.core.constants import (
    DIFF_TRUNCATION_MARKER,
    MAX_DIFF_CHARS,
    TEST_PATH_FRAGMENTS,
)
from devmind.interfaces.sandbox import Sandbox
from devmind.schemas.approval import FileDiffStat
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.workspace_path_guard import WorkspacePathGuard


class DiffService:
    """Reads the working-tree change out of the sandbox for the review payload."""

    def __init__(self, sandbox: Sandbox, guard: WorkspacePathGuard) -> None:
        # `guard` is held for symmetry with the other path-taking services and for a
        # future `paths=` filter; the diff itself is whole-tree and needs no path
        # argument, so there is nothing to resolve through it yet.
        self._sandbox = sandbox
        self._guard = guard

    async def unified_diff(self, workspace: Path) -> str:
        """`git diff` over the whole working tree, capped with a truncation marker."""
        result = await self._sandbox.run(SandboxCommand(argv=("git", "diff")))
        diff = result.stdout
        if len(diff) > MAX_DIFF_CHARS:
            marker = DIFF_TRUNCATION_MARKER.format(limit=MAX_DIFF_CHARS)
            return diff[:MAX_DIFF_CHARS] + marker
        return diff

    async def file_stats(self, workspace: Path) -> list[FileDiffStat]:
        """Per-file added/removed line counts from `git diff --numstat`.

        A binary file's counts come back as `-` from git; they are reported as 0/0.
        """
        result = await self._sandbox.run(SandboxCommand(argv=("git", "diff", "--numstat")))
        stats: list[FileDiffStat] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added_raw, removed_raw, path = parts
            stats.append(
                FileDiffStat(
                    path=path.strip(),
                    added=_count(added_raw),
                    removed=_count(removed_raw),
                )
            )
        return stats

    async def touches_only_tests(self, workspace: Path, profile: RepoProfile) -> bool:
        """True when every changed file is a test file and at least one file changed.

        A tests-only diff means the agent adjusted the tests rather than the code —
        the payload surfaces it as a warning, it is not by itself a rejection.
        """
        stats = await self.file_stats(workspace)
        if not stats:
            return False
        return all(_is_test_path(stat.path, profile.test_paths) for stat in stats)


def _count(raw: str) -> int:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else 0


def _is_test_path(path: str, test_paths: tuple[str, ...]) -> bool:
    normalised = path.replace("\\", "/").strip("/")
    for root in test_paths:
        root = root.replace("\\", "/").strip("/")
        if root and (normalised == root or normalised.startswith(f"{root}/")):
            return True
    segments = normalised.split("/")
    if any(segment in TEST_PATH_FRAGMENTS for segment in segments):
        return True
    basename = segments[-1]
    return basename.startswith("test_") or basename.endswith("_test.py")
