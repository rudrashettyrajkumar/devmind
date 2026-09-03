"""`DiffService` — unified diff, per-file stats, and tests-only detection (E9-F1-T2).

Proves the diff is capped with an explicit marker (a truncated diff is never shown
as complete), numstat parsing including binary files, and the tests-only heuristic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devmind.core.constants import MAX_DIFF_CHARS
from devmind.schemas.repo import RepoProfile
from devmind.services.diff_service import DiffService
from devmind.services.workspace_path_guard import WorkspacePathGuard
from tests.fakes.fake_sandbox import FakeSandbox, command_result

_PROFILE = RepoProfile(language="python", test_paths=("tests",), has_test_suite=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _service(sandbox: FakeSandbox, workspace: Path) -> DiffService:
    return DiffService(sandbox, WorkspacePathGuard(workspace))


async def test_unified_diff_passes_a_short_diff_through(workspace: Path) -> None:
    sandbox = FakeSandbox([command_result(stdout="diff --git a/x b/x\n+one line\n")])
    diff = await _service(sandbox, workspace).unified_diff(workspace)
    assert diff == "diff --git a/x b/x\n+one line\n"
    assert sandbox.commands[0].argv == ("git", "diff")


async def test_unified_diff_truncates_with_a_marker(workspace: Path) -> None:
    huge = "+" + "a" * (MAX_DIFF_CHARS + 500)
    sandbox = FakeSandbox([command_result(stdout=huge)])
    diff = await _service(sandbox, workspace).unified_diff(workspace)
    assert len(diff) < len(huge)
    assert "truncated" in diff
    assert "NOT the full change" in diff


async def test_file_stats_parses_numstat_including_binary(workspace: Path) -> None:
    numstat = "12\t3\tsrc/pkg/mod.py\n-\t-\tassets/logo.png\n0\t7\tREADME.md\n"
    sandbox = FakeSandbox([command_result(stdout=numstat)])
    stats = await _service(sandbox, workspace).file_stats(workspace)

    assert [(s.path, s.added, s.removed) for s in stats] == [
        ("src/pkg/mod.py", 12, 3),
        ("assets/logo.png", 0, 0),
        ("README.md", 0, 7),
    ]
    assert sandbox.commands[0].argv == ("git", "diff", "--numstat")


async def test_touches_only_tests_true_when_every_path_is_a_test(workspace: Path) -> None:
    numstat = "4\t0\ttests/test_parser.py\n2\t1\ttests/conftest.py\n"
    sandbox = FakeSandbox([command_result(stdout=numstat)])
    assert await _service(sandbox, workspace).touches_only_tests(workspace, _PROFILE) is True


async def test_touches_only_tests_false_when_a_source_file_changed(workspace: Path) -> None:
    numstat = "4\t0\ttests/test_parser.py\n9\t2\tsrc/pkg/parser.py\n"
    sandbox = FakeSandbox([command_result(stdout=numstat)])
    assert await _service(sandbox, workspace).touches_only_tests(workspace, _PROFILE) is False


async def test_touches_only_tests_false_on_an_empty_diff(workspace: Path) -> None:
    sandbox = FakeSandbox([command_result(stdout="")])
    assert await _service(sandbox, workspace).touches_only_tests(workspace, _PROFILE) is False
