"""`CodeIndexService` — the gitignore-aware, capped file tree (E4-F3-T1).

`build_tree()` walks the repo breadth-first, sorted, pruning at `max_depth` and
stopping once `max_entries` nodes have been emitted (`FileTree.truncated` records
that it stopped early). It skips `.git`, `node_modules`, `.venv`, `__pycache__`,
binaries, and anything `.gitignore` excludes.
"""

from __future__ import annotations

from pathlib import Path

from devmind.core.constants import BINARY_FILE_EXTENSIONS
from devmind.schemas.repo import FileTree, FileTreeNode
from devmind.services.gitignore_filter import GitignoreFilter


class CodeIndexService:
    """Builds a compact structural view of a repository on disk."""

    def build_tree(self, root: Path, *, max_depth: int, max_entries: int) -> FileTree:
        gitignore = GitignoreFilter.for_root(root)
        counter = _EntryBudget(max_entries)
        root_node = self._build_node(
            root, root, gitignore, depth=0, max_depth=max_depth, budget=counter
        )
        return FileTree(root=root_node, entry_count=counter.used, truncated=counter.exceeded)

    def _build_node(
        self,
        path: Path,
        repo_root: Path,
        gitignore: GitignoreFilter,
        *,
        depth: int,
        max_depth: int,
        budget: _EntryBudget,
    ) -> FileTreeNode:
        name = path.name or path.as_posix()
        if not path.is_dir() or path.is_symlink():
            return FileTreeNode(name=name, is_dir=False)
        if depth >= max_depth:
            return FileTreeNode(name=name, is_dir=True)

        children: list[FileTreeNode] = []
        for child in sorted(path.iterdir(), key=lambda entry: entry.name):
            if child.is_symlink():
                continue
            rel = child.relative_to(repo_root)
            is_dir = child.is_dir()
            if gitignore.ignores(rel, is_dir=is_dir):
                continue
            if not is_dir and child.suffix.lower() in BINARY_FILE_EXTENSIONS:
                continue
            if not budget.take():
                break
            children.append(
                self._build_node(
                    child,
                    repo_root,
                    gitignore,
                    depth=depth + 1,
                    max_depth=max_depth,
                    budget=budget,
                )
            )
        return FileTreeNode(name=name, is_dir=True, children=tuple(children))


class _EntryBudget:
    """A shared counter for the tree walk: how many nodes may still be emitted."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.used = 0
        self.exceeded = False

    def take(self) -> bool:
        if self.used >= self._limit:
            self.exceeded = True
            return False
        self.used += 1
        return True
