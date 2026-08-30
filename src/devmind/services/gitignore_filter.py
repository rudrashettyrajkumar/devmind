"""A pragmatic `.gitignore` matcher for the code index (E4).

Not a full reimplementation of gitignore semantics — DevMind only needs to keep the
file tree and the symbol index free of build artefacts and vendored code. It handles
the cases that actually matter: comments and blanks, a leading `!` negation, a
trailing `/` (directory-only), an anchoring leading `/`, and `fnmatch`-style globs
either on the basename or on a path containing `/`. Plus a hard-coded set of
directories (`.git`, `node_modules`, `.venv`, …) that are always skipped.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from devmind.core.constants import INDEX_IGNORE_DIRS


class GitignoreFilter:
    """Decides whether a repo-relative path is ignored."""

    def __init__(self, patterns: list[str], ignore_dirs: frozenset[str]) -> None:
        self._ignore_dirs = ignore_dirs
        self._negations: list[str] = []
        self._patterns: list[str] = []
        for pattern in patterns:
            if pattern.startswith("!"):
                self._negations.append(pattern[1:])
            else:
                self._patterns.append(pattern)

    @classmethod
    def for_root(cls, root: Path) -> GitignoreFilter:
        """Build a filter from `<root>/.gitignore` (if present) plus the always-skip set."""
        patterns: list[str] = []
        gitignore = root / ".gitignore"
        if gitignore.is_file():
            for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    patterns.append(stripped)
        return cls(patterns, INDEX_IGNORE_DIRS)

    def ignores(self, rel_path: Path, *, is_dir: bool) -> bool:
        """True if `rel_path` (relative to the repo root) should be skipped."""
        parts = rel_path.parts
        if any(part in self._ignore_dirs for part in parts):
            return True

        matched = any(self._matches(pattern, rel_path, is_dir=is_dir) for pattern in self._patterns)
        if not matched:
            return False
        negated = any(
            self._matches(pattern, rel_path, is_dir=is_dir) for pattern in self._negations
        )
        return not negated

    @staticmethod
    def _matches(pattern: str, rel_path: Path, *, is_dir: bool) -> bool:
        directory_only = pattern.endswith("/")
        body = pattern.rstrip("/")
        if directory_only and not is_dir:
            return False
        if not body:
            return False

        as_posix = rel_path.as_posix()
        if body.startswith("/"):
            return fnmatch(as_posix, body.lstrip("/"))
        if "/" in body:
            return fnmatch(as_posix, body) or fnmatch(as_posix, f"*/{body}")
        return any(fnmatch(part, body) for part in rel_path.parts)
