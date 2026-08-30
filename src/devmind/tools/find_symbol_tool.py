"""`find_symbol` — locate a class or function by exact name, via `SymbolIndexer`.

Re-indexes the workspace on each call rather than reusing the ingestion-time index:
the agent edits files between calls, so symbols move. `SymbolIndexer` is `ast`-only —
it never imports or executes the repo.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import FindSymbolInput, ToolResult
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Find where a class or function is defined. Pass the exact `name`; optionally "
    "restrict to `kind` ('class' or 'function'). Returns `module:line  kind  name` "
    "for every match. Use it instead of guessing a file path."
)


class FindSymbolTool(Tool):
    def __init__(self, indexer: SymbolIndexer) -> None:
        self._indexer = indexer

    @property
    def name(self) -> ToolName:
        return ToolName.FIND_SYMBOL

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return FindSymbolInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, FindSymbolInput)
        index = self._indexer.index(ctx.workspace)

        matches: list[str] = []
        for module in index.modules:
            for symbol in module.symbols:
                if symbol.name != payload.name:
                    continue
                if payload.kind is not None and symbol.kind is not payload.kind:
                    continue
                matches.append(
                    f"{module.module}:{symbol.lineno}  {symbol.kind.value}  {symbol.name}"
                )

        if not matches:
            return ToolResult(
                content=f"no symbol named {payload.name!r} found", metadata={"matches": 0}
            )
        return ToolResult(content="\n".join(matches), metadata={"matches": len(matches)})
