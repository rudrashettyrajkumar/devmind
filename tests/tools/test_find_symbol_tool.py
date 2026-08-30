from __future__ import annotations

from devmind.core.enums import SymbolKind
from devmind.schemas.tools import FindSymbolInput
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.tools.find_symbol_tool import FindSymbolTool
from devmind.tools.tool_context import ToolContext


async def test_finds_a_class_with_module_and_line(tool_context: ToolContext) -> None:
    result = await FindSymbolTool(SymbolIndexer()).execute(
        FindSymbolInput(name="Calculator"), tool_context
    )
    assert not result.is_error
    assert "src/pkg/calc.py:1" in result.content
    assert "class" in result.content
    assert result.metadata["matches"] == 1


async def test_kind_filter_excludes_non_matching(tool_context: ToolContext) -> None:
    result = await FindSymbolTool(SymbolIndexer()).execute(
        FindSymbolInput(name="Calculator", kind=SymbolKind.FUNCTION), tool_context
    )
    assert result.metadata["matches"] == 0


async def test_unknown_symbol_is_not_an_error(tool_context: ToolContext) -> None:
    result = await FindSymbolTool(SymbolIndexer()).execute(
        FindSymbolInput(name="Nonexistent"), tool_context
    )
    assert not result.is_error
    assert "no symbol named" in result.content
