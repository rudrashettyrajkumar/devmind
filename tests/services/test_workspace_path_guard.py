"""Adversarial tests for `WorkspacePathGuard` — the sole enforcement of SI-5.

These are the highest-value tests in E4. Every known escape vector must raise
`PathEscapeError`; only a plain relative path landing inside the workspace, without
crossing a symlink, is allowed through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.services.workspace_path_guard import WorkspacePathGuard


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace" / "session-1"
    root.mkdir(parents=True)
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "mod.py").write_text("x = 1\n")
    return root


@pytest.fixture
def guard(workspace: Path) -> WorkspacePathGuard:
    return WorkspacePathGuard(workspace)


# --- the allowed case -----------------------------------------------------------


def test_plain_nested_relative_path_resolves(guard: WorkspacePathGuard, workspace: Path) -> None:
    resolved = guard.resolve("src/pkg/mod.py")
    assert resolved == (workspace / "src" / "pkg" / "mod.py").resolve()
    assert resolved.is_relative_to(workspace.resolve())


def test_path_to_a_not_yet_created_file_resolves(
    guard: WorkspacePathGuard, workspace: Path
) -> None:
    resolved = guard.resolve("src/pkg/new_file.py")
    assert resolved == (workspace / "src" / "pkg" / "new_file.py").resolve()


def test_empty_candidate_resolves_to_the_root(guard: WorkspacePathGuard, workspace: Path) -> None:
    assert guard.resolve("") == workspace.resolve()


def test_inner_dot_dot_that_stays_inside_is_still_rejected(guard: WorkspacePathGuard) -> None:
    # `src/../src/pkg/mod.py` would resolve inside, but '..' is refused outright.
    with pytest.raises(PathEscapeError):
        guard.resolve("src/../src/pkg/mod.py")


# --- traversal ----------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "../../etc/passwd",
        "../sibling/file",
        "a/../../..",
        "a/b/../../../c",
        "..",
        "./../x",
    ],
)
def test_parent_traversal_is_rejected(guard: WorkspacePathGuard, candidate: str) -> None:
    with pytest.raises(PathEscapeError):
        guard.resolve(candidate)


# --- absolute paths ---------------------------------------------------------------


def test_absolute_path_outside_is_rejected(guard: WorkspacePathGuard) -> None:
    with pytest.raises(PathEscapeError):
        guard.resolve("/etc/passwd")


def test_absolute_path_even_inside_the_workspace_is_rejected(
    guard: WorkspacePathGuard, workspace: Path
) -> None:
    inside = str(workspace / "src" / "pkg" / "mod.py")
    with pytest.raises(PathEscapeError):
        guard.resolve(inside)


# --- symlinks ---------------------------------------------------------------------


def test_symlink_pointing_out_of_the_workspace_is_rejected(
    guard: WorkspacePathGuard, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "escape").symlink_to("/tmp")
    with pytest.raises(PathEscapeError):
        guard.resolve("escape")
    with pytest.raises(PathEscapeError):
        guard.resolve("escape/evil.txt")


def test_symlinked_directory_pointing_back_inside_is_still_rejected(
    guard: WorkspacePathGuard, workspace: Path
) -> None:
    (workspace / "real").mkdir()
    (workspace / "alias").symlink_to(workspace / "real")
    with pytest.raises(PathEscapeError):
        guard.resolve("alias/file.py")


def test_symlink_as_an_intermediate_component_is_rejected(
    guard: WorkspacePathGuard, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "src" / "linked").symlink_to(outside)
    with pytest.raises(PathEscapeError):
        guard.resolve("src/linked/whatever.py")


# --- prefix / sibling attacks -------------------------------------------------


def test_sibling_directory_sharing_a_name_prefix_is_not_reachable(
    tmp_path: Path, workspace: Path
) -> None:
    # `.../workspace/session-1` vs a sibling `.../workspace/session-1-evil`:
    # a string-prefix check would be fooled; is_relative_to is not.
    evil = workspace.parent / "session-1-evil"
    evil.mkdir()
    (evil / "loot.txt").write_text("x")
    guard = WorkspacePathGuard(workspace)
    with pytest.raises(PathEscapeError):
        guard.resolve("../session-1-evil/loot.txt")


# --- construction -------------------------------------------------------------


def test_guard_on_a_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        WorkspacePathGuard(tmp_path / "does-not-exist")


def test_root_property_is_resolved(workspace: Path) -> None:
    assert WorkspacePathGuard(workspace).root == workspace.resolve()
