"""`WorkspacePathGuard` — the sole enforcement of safety invariant SI-5.

Every path-taking tool the agent can call resolves its argument through this class
before touching the filesystem. It is the most security-relevant code in DevMind, so
it is deliberately strict and deliberately dumb: reject anything that is not a plain
relative path landing, without following a symlink, inside the workspace root.

The check is `Path.resolve()` + `is_relative_to(root)` — never string prefix
matching. `/workspace-evil` starts with `/workspace`; `is_relative_to` is not fooled.
On top of that, four syntactic/structural rejections that a resolve-only check would
let through or that harden it against TOCTOU:

  * absolute paths — always rejected, even one that points inside the workspace;
  * any `..` component — rejected outright, not "rejected if it happens to escape";
  * any symlink among the traversed components — rejected regardless of target, so a
    symlinked directory pointing back *inside* the workspace is still refused;
  * the belt-and-braces `is_relative_to` check on the fully resolved path.
"""

from pathlib import Path

from devmind.exceptions import PathEscapeError


class WorkspacePathGuard:
    """Resolves a candidate path inside one workspace, or raises `PathEscapeError`."""

    def __init__(self, workspace_root: Path) -> None:
        # `strict=True`: the workspace must already exist. A guard for a directory
        # that isn't there is a bug in the caller, not something to paper over.
        self._root = workspace_root.resolve(strict=True)

    @property
    def root(self) -> Path:
        """The resolved workspace root every candidate is checked against."""
        return self._root

    def resolve(self, candidate: str | Path) -> Path:
        """Return the absolute path `candidate` names inside the workspace.

        Raises `PathEscapeError` — and touches nothing — if `candidate` is absolute,
        contains `..`, traverses a symlink, or otherwise resolves outside the root.
        """
        raw = Path(candidate)

        if raw.is_absolute():
            raise self._escape(candidate, "absolute paths are not allowed")
        if ".." in raw.parts:
            raise self._escape(candidate, "parent-directory ('..') components are not allowed")

        self._reject_symlink_components(candidate, raw)

        resolved = (self._root / raw).resolve()
        if not resolved.is_relative_to(self._root):
            raise self._escape(candidate, "path resolves outside the workspace root")
        return resolved

    def _reject_symlink_components(self, candidate: str | Path, raw: Path) -> None:
        """Walk the candidate one component at a time against the *unresolved* tree
        and refuse the first symlink seen — file or directory, pointing anywhere.
        """
        probe = self._root
        for part in raw.parts:
            probe = probe / part
            if probe.is_symlink():
                raise self._escape(candidate, f"path traverses a symlink at {part!r}")

    def _escape(self, candidate: str | Path, why: str) -> PathEscapeError:
        return PathEscapeError(
            f"path {str(candidate)!r} rejected: {why}",
            details={"candidate": str(candidate), "workspace_root": str(self._root), "reason": why},
        )
