from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.schemas.tools import WriteFileInput
from devmind.tools.tool_context import ToolContext
from devmind.tools.write_file_tool import WriteFileTool


async def test_writes_and_creates_parents(tool_context: ToolContext, workspace: Path) -> None:
    result = await WriteFileTool().execute(
        WriteFileInput(path="src/pkg/new/mod.py", content="x = 1\n"), tool_context
    )
    assert not result.is_error
    assert (workspace / "src" / "pkg" / "new" / "mod.py").read_text() == "x = 1\n"
    assert result.metadata["bytes_written"] == 6


async def test_overwrites_existing(tool_context: ToolContext, workspace: Path) -> None:
    await WriteFileTool().execute(
        WriteFileInput(path="src/pkg/calc.py", content="print('new')\n"), tool_context
    )
    assert (workspace / "src" / "pkg" / "calc.py").read_text() == "print('new')\n"


async def test_directory_target_is_an_error(tool_context: ToolContext) -> None:
    result = await WriteFileTool().execute(WriteFileInput(path="src", content="x"), tool_context)
    assert result.is_error


async def test_size_cap_rejects(tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("devmind.tools.write_file_tool.WRITE_FILE_MAX_BYTES", 10)
    result = await WriteFileTool().execute(
        WriteFileInput(path="big.txt", content="x" * 50), tool_context
    )
    assert result.is_error
    assert "refusing to write" in result.content


async def test_path_escape_raises(tool_context: ToolContext) -> None:
    with pytest.raises(PathEscapeError):
        await WriteFileTool().execute(
            WriteFileInput(path="../escape.txt", content="x"), tool_context
        )
