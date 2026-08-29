from __future__ import annotations

from pathlib import Path

import pytest

from devmind.schemas.repo import FileTreeNode
from devmind.services.code_index_service import CodeIndexService


@pytest.fixture
def service() -> CodeIndexService:
    return CodeIndexService()


def _names(node: FileTreeNode) -> set[str]:
    found = {node.name}
    for child in node.children:
        found |= _names(child)
    return found


def test_tree_reflects_layout_sorted(service: CodeIndexService, tree_dir: Path) -> None:
    tree = service.build_tree(tree_dir, max_depth=5, max_entries=1000)
    top = [child.name for child in tree.root.children]
    assert top == sorted(top)
    assert "pkg" in top
    assert "app.js" in top


def test_gitignored_and_vendored_paths_are_excluded(
    service: CodeIndexService, tree_dir: Path
) -> None:
    tree = service.build_tree(tree_dir, max_depth=5, max_entries=1000)
    names = _names(tree.root)
    assert "debug.log" not in names
    assert "node_modules" not in names


def test_binary_files_are_excluded(service: CodeIndexService, tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
    tree = service.build_tree(tmp_path, max_depth=3, max_entries=100)
    names = _names(tree.root)
    assert "keep.py" in names
    assert "image.png" not in names


def test_max_depth_prunes_children(service: CodeIndexService, tree_dir: Path) -> None:
    tree = service.build_tree(tree_dir, max_depth=1, max_entries=1000)
    pkg = next(child for child in tree.root.children if child.name == "pkg")
    assert pkg.is_dir
    assert pkg.children == ()


def test_max_entries_sets_truncated(service: CodeIndexService, tree_dir: Path) -> None:
    tree = service.build_tree(tree_dir, max_depth=5, max_entries=2)
    assert tree.truncated is True
    assert tree.entry_count == 2


def test_symlinks_are_not_followed(service: CodeIndexService, tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")
    tree = service.build_tree(tmp_path, max_depth=3, max_entries=100)
    assert "link.py" not in _names(tree.root)
