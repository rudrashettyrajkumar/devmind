from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.schemas.tools import ListDirInput
from devmind.tools.list_dir_tool import ListDirTool
from devmind.tools.tool_context import ToolContext


async def test_lists_tree_and_respects_gitignore(tool_context: ToolContext) -> None:
    result = await ListDirTool().execute(ListDirInput(path=".", depth=3), tool_context)
    assert not result.is_error
    assert "src/" in result.content
    assert "calc.py" in result.content
    assert "debug.log" not in result.content  # gitignored


async def test_not_a_directory_is_an_error(tool_context: ToolContext) -> None:
    result = await ListDirTool().execute(ListDirInput(path="README.md"), tool_context)
    assert result.is_error


async def test_path_escape_raises(tool_context: ToolContext) -> None:
    with pytest.raises(PathEscapeError):
        await ListDirTool().execute(ListDirInput(path="../../etc"), tool_context)


async def test_symlinks_are_not_listed(tool_context: ToolContext, workspace: Path) -> None:
    (workspace / "real.txt").write_text("x")
    (workspace / "link.txt").symlink_to(workspace / "real.txt")
    result = await ListDirTool().execute(ListDirInput(path=".", depth=1), tool_context)
    assert "real.txt" in result.content
    assert "link.txt" not in result.content


async def test_entry_cap_marks_truncation(
    tool_context: ToolContext, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = workspace / "many"
    big.mkdir()
    for i in range(50):
        (big / f"f{i:03d}.txt").write_text("x")
    monkeypatch.setattr("devmind.tools.list_dir_tool.LIST_DIR_MAX_ENTRIES", 5)
    result = await ListDirTool().execute(ListDirInput(path="many", depth=1), tool_context)
    assert result.metadata["truncated"] is True
