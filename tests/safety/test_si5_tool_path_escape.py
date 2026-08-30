"""SI-5 (E6 surface): every path-taking tool rejects every workspace-escape vector.

The guard itself is proven in `test_si5_workspace_path_guard.py`; this checks that
each tool actually routes its path argument through `ctx.guard` and that the executor
turns the resulting `PathEscapeError` into an `is_error` result the agent can read.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from devmind.schemas.llm import ToolCall
from devmind.services.output_truncator import OutputTruncator
from devmind.services.tool_executor import ToolExecutor
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.apply_patch_tool import ApplyPatchTool
from devmind.tools.git_diff_tool import GitDiffTool
from devmind.tools.list_dir_tool import ListDirTool
from devmind.tools.read_file_tool import ReadFileTool
from devmind.tools.tool_context import ToolContext
from devmind.tools.write_file_tool import WriteFileTool

_ESCAPES = ["../../etc/passwd", "/etc/passwd", "a/../../../root", "../sibling"]

_TOOL_ARGS: dict[str, Callable[[str], dict[str, object]]] = {
    "list_dir": lambda p: {"path": p},
    "read_file": lambda p: {"path": p},
    "write_file": lambda p: {"path": p, "content": "x"},
    "apply_patch": lambda p: {"path": p, "old_string": "a", "new_string": "b"},
    "git_diff": lambda p: {"paths": [p]},
}


@pytest.fixture
def executor(tool_context: ToolContext) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register_all(
        [ListDirTool(), ReadFileTool(), WriteFileTool(), ApplyPatchTool(), GitDiffTool()]
    )
    return ToolExecutor(registry, tool_context.events, OutputTruncator(2_000))


@pytest.mark.parametrize("tool_name", list(_TOOL_ARGS))
@pytest.mark.parametrize("escape", _ESCAPES)
async def test_si5_path_taking_tool_rejects_escape(
    executor: ToolExecutor, tool_context: ToolContext, tool_name: str, escape: str
) -> None:
    call = ToolCall(id="c1", name=tool_name, arguments=dict(_TOOL_ARGS[tool_name](escape)))
    block = await executor.execute(call, tool_context)
    assert block.is_error
