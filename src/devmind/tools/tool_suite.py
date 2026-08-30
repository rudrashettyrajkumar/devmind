"""Builds the full `ToolRegistry` — the complete agent capability surface (E6).

This is the single place the agent's hands are assembled. The registry-safety test
(SI-1) iterates exactly what this returns: if a remote-capable tool were ever added,
it would land here and the test would fail.
"""

from __future__ import annotations

from devmind.services.code_search_service import CodeSearchService
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.apply_patch_tool import ApplyPatchTool
from devmind.tools.find_symbol_tool import FindSymbolTool
from devmind.tools.finish_tool import FinishTool
from devmind.tools.git_diff_tool import GitDiffTool
from devmind.tools.list_dir_tool import ListDirTool
from devmind.tools.read_file_tool import ReadFileTool
from devmind.tools.run_command_tool import RunCommandTool
from devmind.tools.run_tests_tool import RunTestsTool
from devmind.tools.search_code_tool import SearchCodeTool
from devmind.tools.todo_write_tool import TodoWriteTool
from devmind.tools.write_file_tool import WriteFileTool


def build_tool_registry(*, search: CodeSearchService, indexer: SymbolIndexer) -> ToolRegistry:
    """Every tool the agent can call, registered. `search` and `indexer` are the only
    tools with dependencies; the rest work off `ToolContext` alone.
    """
    registry = ToolRegistry()
    registry.register_all(
        [
            ListDirTool(),
            ReadFileTool(),
            SearchCodeTool(search),
            FindSymbolTool(indexer),
            WriteFileTool(),
            ApplyPatchTool(),
            RunCommandTool(),
            RunTestsTool(),
            GitDiffTool(),
            TodoWriteTool(),
            FinishTool(),
        ]
    )
    return registry
