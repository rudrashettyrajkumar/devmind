from __future__ import annotations

from pathlib import Path

import pytest

from devmind.exceptions import PathEscapeError
from devmind.schemas.tools import ApplyPatchInput
from devmind.tools.apply_patch_tool import ApplyPatchTool
from devmind.tools.tool_context import ToolContext


async def test_single_match_replaces(tool_context: ToolContext, workspace: Path) -> None:
    result = await ApplyPatchTool().execute(
        ApplyPatchInput(
            path="src/pkg/calc.py", old_string="return a - b", new_string="return a + b"
        ),
        tool_context,
    )
    assert not result.is_error
    assert "return a + b" in (workspace / "src" / "pkg" / "calc.py").read_text()


async def test_zero_matches_errors_with_nearby_context(
    tool_context: ToolContext,
) -> None:
    result = await ApplyPatchTool().execute(
        ApplyPatchInput(
            path="src/pkg/calc.py", old_string="return a - b  # comment", new_string="x"
        ),
        tool_context,
    )
    assert result.is_error
    assert "was not found" in result.content
    assert "closest text" in result.content  # anchor located


async def test_zero_matches_no_anchor(tool_context: ToolContext) -> None:
    result = await ApplyPatchTool().execute(
        ApplyPatchInput(
            path="src/pkg/calc.py", old_string="totally unrelated text", new_string="x"
        ),
        tool_context,
    )
    assert result.is_error
    assert "was not found" in result.content


async def test_multiple_matches_errors_and_does_not_write(
    tool_context: ToolContext, workspace: Path
) -> None:
    target = workspace / "dup.py"
    target.write_text("value = 1\nvalue = 1\n")
    result = await ApplyPatchTool().execute(
        ApplyPatchInput(path="dup.py", old_string="value = 1", new_string="value = 2"),
        tool_context,
    )
    assert result.is_error
    assert "matched 2 times" in result.content
    assert target.read_text() == "value = 1\nvalue = 1\n"


async def test_missing_file_is_an_error(tool_context: ToolContext) -> None:
    result = await ApplyPatchTool().execute(
        ApplyPatchInput(path="nope.py", old_string="a", new_string="b"), tool_context
    )
    assert result.is_error


async def test_path_escape_raises(tool_context: ToolContext) -> None:
    with pytest.raises(PathEscapeError):
        await ApplyPatchTool().execute(
            ApplyPatchInput(path="../../etc/hosts", old_string="a", new_string="b"),
            tool_context,
        )
