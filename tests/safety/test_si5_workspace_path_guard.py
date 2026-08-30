"""SI-5: all file writes stay inside the session workspace.

`WorkspacePathGuard.resolve()` is the single mechanism enforcing this. The full
adversarial matrix lives in `tests/services/test_workspace_path_guard.py`; these are
the named invariant checks that must never regress. A change that breaks one of these
is a broken invariant — fix the code, never the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.services.workspace_manager import WorkspaceManager
from devmind.services.workspace_path_guard import WorkspacePathGuard


@pytest.fixture
def guard(tmp_path: Path) -> WorkspacePathGuard:
    root = tmp_path / "ws" / "session"
    root.mkdir(parents=True)
    return WorkspacePathGuard(root)


def test_si5_contained_relative_paths_are_allowed(guard: WorkspacePathGuard) -> None:
    resolved = guard.resolve("pkg/module.py")
    assert resolved.is_relative_to(guard.root)


def test_si5_dot_dot_traversal_cannot_escape(guard: WorkspacePathGuard) -> None:
    with pytest.raises(PathEscapeError):
        guard.resolve("../../../etc/passwd")


def test_si5_absolute_paths_are_refused(guard: WorkspacePathGuard) -> None:
    with pytest.raises(PathEscapeError):
        guard.resolve("/etc/passwd")


def test_si5_symlink_out_of_workspace_is_refused(guard: WorkspacePathGuard) -> None:
    (guard.root / "leak").symlink_to("/tmp")
    with pytest.raises(PathEscapeError):
        guard.resolve("leak/secret")


def test_si5_every_workspace_gets_an_enforcing_guard(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=10 * 1024**3)
    manager.create("s1")
    with pytest.raises(PathEscapeError):
        manager.guard_for("s1").resolve("../s1-evil/x")
