"""`search_code` — ripgrep/grep over the workspace, delegated to `CodeSearchService`."""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import SearchCodeInput, ToolResult
from devmind.services.code_search_service import CodeSearchService
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Search the workspace for a regular expression. Optionally restrict to a path "
    "glob (e.g. '*.py'). Returns matching lines as `path:line: text`, capped at "
    "`max_results`. Use it to find where something is used."
)


class SearchCodeTool(Tool):
    def __init__(self, search: CodeSearchService) -> None:
        self._search = search

    @property
    def name(self) -> ToolName:
        return ToolName.SEARCH_CODE

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return SearchCodeInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, SearchCodeInput)
        hits = await self._search.search(
            ctx.workspace,
            payload.pattern,
            glob=payload.glob,
            max_results=payload.max_results,
        )
        if not hits:
            return ToolResult(content=f"no matches for {payload.pattern!r}", metadata={"hits": 0})
        body = "\n".join(f"{hit.path}:{hit.line}: {hit.text}" for hit in hits)
        return ToolResult(content=body, metadata={"hits": len(hits)})
