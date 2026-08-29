"""`RepoBriefBuilder` — assembles the cacheable `RepoBrief` (E4-F3-T4).

The brief sits inside the cached system prefix (E3-F2-T1), so its output must be
deterministic for a fixed commit and stay within a ~2,000-token budget. This builder
takes the already-computed profile, file tree, and symbol index and folds them into
the small fixed shape `RepoBrief` renders — trimming each part to a hard line/entry
cap so the rendered block never blows the budget.
"""

from __future__ import annotations

from pathlib import Path

from devmind.core.constants import (
    ENTRY_POINT_FILENAMES,
    REPO_BRIEF_MAX_ENTRY_POINTS,
    REPO_BRIEF_MAX_KEY_MODULES,
    REPO_BRIEF_MAX_TREE_LINES,
    REPO_BRIEF_TREE_DEPTH,
)
from devmind.schemas.repo import FileTree, FileTreeNode, RepoBrief, RepoProfile, SymbolIndex


class RepoBriefBuilder:
    """Builds one `RepoBrief` from the ingestion artefacts."""

    def build(
        self,
        *,
        repo_url: str,
        profile: RepoProfile,
        file_tree: FileTree,
        symbol_index: SymbolIndex,
        root: Path,
    ) -> RepoBrief:
        return RepoBrief(
            repo_name=self._repo_name(repo_url),
            language=profile.language,
            test_framework=profile.test_framework,
            test_command=profile.test_command,
            tree_preview=self._tree_preview(file_tree.root),
            key_modules=self._key_modules(symbol_index),
            entry_points=self._entry_points(root, profile),
        )

    @staticmethod
    def _repo_name(repo_url: str) -> str:
        tail = repo_url.rstrip("/").split("/")[-1]
        tail = tail.split(":")[-1]
        return tail.removesuffix(".git") or repo_url

    @staticmethod
    def _tree_preview(root: FileTreeNode) -> str:
        lines: list[str] = []

        def walk(node: FileTreeNode, depth: int) -> None:
            if len(lines) >= REPO_BRIEF_MAX_TREE_LINES:
                return
            for child in node.children:
                marker = "/" if child.is_dir else ""
                lines.append(f"{'  ' * depth}{child.name}{marker}")
                if child.is_dir and depth + 1 < REPO_BRIEF_TREE_DEPTH:
                    walk(child, depth + 1)

        walk(root, 0)
        return "\n".join(lines)

    @staticmethod
    def _key_modules(symbol_index: SymbolIndex) -> tuple[str, ...]:
        ordered = sorted(
            symbol_index.modules,
            key=lambda module: (-len(module.symbols), module.module),
        )
        return tuple(module.module for module in ordered[:REPO_BRIEF_MAX_KEY_MODULES])

    @staticmethod
    def _entry_points(root: Path, profile: RepoProfile) -> tuple[str, ...]:
        found: set[str] = set()
        for name in ENTRY_POINT_FILENAMES:
            if (root / name).is_file():
                found.add(name)
        for package in profile.package_dirs:
            for name in ENTRY_POINT_FILENAMES:
                candidate = root / package / name
                if candidate.is_file():
                    found.add(f"{package}/{name}")
        return tuple(sorted(found))[:REPO_BRIEF_MAX_ENTRY_POINTS]
