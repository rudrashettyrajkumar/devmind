from __future__ import annotations

from pathlib import Path

from devmind.schemas.repo import SearchHit
from devmind.schemas.tools import SearchCodeInput
from devmind.tools.search_code_tool import SearchCodeTool
from devmind.tools.tool_context import ToolContext


class _FakeSearch:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.calls: list[tuple[Path, str, str | None, int]] = []

    async def search(
        self, root: Path, pattern: str, *, glob: str | None = None, max_results: int = 100
    ) -> list[SearchHit]:
        self.calls.append((root, pattern, glob, max_results))
        return self._hits[:max_results]


async def test_formats_hits_as_path_line_text(tool_context: ToolContext) -> None:
    fake = _FakeSearch([SearchHit(path="a.py", line=3, text="do_thing()")])
    result = await SearchCodeTool(fake).execute(SearchCodeInput(pattern="thing"), tool_context)
    assert result.content == "a.py:3: do_thing()"
    assert result.metadata["hits"] == 1


async def test_no_matches_is_not_an_error(tool_context: ToolContext) -> None:
    result = await SearchCodeTool(_FakeSearch([])).execute(
        SearchCodeInput(pattern="absent"), tool_context
    )
    assert not result.is_error
    assert result.metadata["hits"] == 0


async def test_passes_glob_and_max_results_through(tool_context: ToolContext) -> None:
    fake = _FakeSearch([])
    await SearchCodeTool(fake).execute(
        SearchCodeInput(pattern="p", glob="*.py", max_results=10), tool_context
    )
    _, pattern, glob, max_results = fake.calls[0]
    assert (pattern, glob, max_results) == ("p", "*.py", 10)
