from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError, WorkspaceError
from devmind.services.workspace_manager import WorkspaceManager
from devmind.services.workspace_path_guard import WorkspacePathGuard

_HUGE = 10 * 1024**3


def test_create_makes_the_session_directory(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=_HUGE)
    path = manager.create("session-abc")
    assert path == tmp_path / "root" / "session-abc"
    assert path.is_dir()


def test_create_twice_for_the_same_session_raises(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=_HUGE)
    manager.create("dup")
    with pytest.raises(WorkspaceError):
        manager.create("dup")


def test_create_refuses_once_the_root_is_over_its_ceiling(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "big.bin").write_bytes(b"x" * 5_000)
    manager = WorkspaceManager(root, max_bytes=1_000)
    with pytest.raises(WorkspaceError) as excinfo:
        manager.create("s1")
    assert "ceiling" in str(excinfo.value)


def test_usage_bytes_sums_regular_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    manager = WorkspaceManager(root, max_bytes=_HUGE)
    ws = manager.create("s1")
    (ws / "a.txt").write_bytes(b"a" * 100)
    (ws / "nested").mkdir()
    (ws / "nested" / "b.txt").write_bytes(b"b" * 50)
    assert manager.usage_bytes() == 150


def test_usage_bytes_is_zero_before_the_root_exists(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "missing", max_bytes=_HUGE)
    assert manager.usage_bytes() == 0


def test_guard_for_returns_a_guard_scoped_to_the_session(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=_HUGE)
    ws = manager.create("s1")
    guard = manager.guard_for("s1")
    assert isinstance(guard, WorkspacePathGuard)
    assert guard.root == ws.resolve()
    with pytest.raises(PathEscapeError):
        guard.resolve("../s1/../../etc/passwd")


def test_destroy_removes_the_workspace_and_is_idempotent(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=_HUGE)
    manager.create("s1")
    manager.destroy("s1")
    assert not (tmp_path / "root" / "s1").exists()
    manager.destroy("s1")  # no error the second time


@pytest.mark.parametrize("bad", ["../evil", "a/b", "..", "", "with/slash"])
def test_unsafe_session_ids_are_rejected(tmp_path: Path, bad: str) -> None:
    manager = WorkspaceManager(tmp_path / "root", max_bytes=_HUGE)
    with pytest.raises(WorkspaceError):
        manager.create(bad)
