from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.schemas.tools import ReadFileInput
from devmind.tools.read_file_tool import ReadFileTool
from devmind.tools.tool_context import ToolContext


async def test_reads_with_line_numbers(tool_context: ToolContext) -> None:
    result = await ReadFileTool().execute(ReadFileInput(path="src/pkg/calc.py"), tool_context)
    assert not result.is_error
    assert "     1  class Calculator:" in result.content
    assert result.metadata["total_lines"] == 3


async def test_line_range_slices(tool_context: ToolContext) -> None:
    result = await ReadFileTool().execute(
        ReadFileInput(path="src/pkg/calc.py", start_line=2, end_line=2), tool_context
    )
    assert "def add" in result.content
    assert "class Calculator" not in result.content
    assert result.content.startswith("     2  ")


async def test_reversed_range_is_an_error(tool_context: ToolContext) -> None:
    result = await ReadFileTool().execute(
        ReadFileInput(path="src/pkg/calc.py", start_line=3, end_line=1), tool_context
    )
    assert result.is_error


async def test_missing_file_is_an_error(tool_context: ToolContext) -> None:
    result = await ReadFileTool().execute(ReadFileInput(path="nope.py"), tool_context)
    assert result.is_error


async def test_binary_by_extension_is_rejected(tool_context: ToolContext, workspace: Path) -> None:
    (workspace / "logo.png").write_bytes(b"\x89PNG\r\n\x00stuff")
    result = await ReadFileTool().execute(ReadFileInput(path="logo.png"), tool_context)
    assert result.is_error
    assert "binary" in result.content


async def test_binary_by_nul_bytes_is_rejected(tool_context: ToolContext, workspace: Path) -> None:
    (workspace / "data.bin2").write_bytes(b"text\x00more")
    result = await ReadFileTool().execute(ReadFileInput(path="data.bin2"), tool_context)
    assert result.is_error


async def test_oversized_file_is_capped(
    tool_context: ToolContext, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (workspace / "big.py").write_text("\n".join(f"x = {i}" for i in range(500)))
    monkeypatch.setattr("devmind.tools.read_file_tool.MAX_FILE_READ_LINES", 10)
    result = await ReadFileTool().execute(ReadFileInput(path="big.py"), tool_context)
    assert result.metadata["truncated"] is True
    assert "truncated after 10 lines" in result.content


async def test_path_escape_raises(tool_context: ToolContext) -> None:
    with pytest.raises(PathEscapeError):
        await ReadFileTool().execute(ReadFileInput(path="/etc/passwd"), tool_context)
