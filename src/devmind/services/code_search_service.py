"""`CodeSearchService` — ripgrep with a `grep -rn` fallback (E4-F3-T3).

`rg --json` when ripgrep is on PATH, `grep -rn` otherwise. Results are returned as
structured `SearchHit`s, capped at `max_results`, with each line truncated so one
unlucky minified file cannot blow the context window. Runs through the injected
`CommandRunner` (argv-only, time-bounded); no network, no shell.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from devmind.core.constants import (
    CODE_SEARCH_MAX_LINE_CHARS,
    CODE_SEARCH_MAX_RESULTS,
    CODE_SEARCH_TIMEOUT_SECONDS,
)
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.repo import SearchHit

logger = logging.getLogger(__name__)


class CodeSearchService:
    """Text search over a workspace, structured and bounded."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    async def search(
        self,
        root: Path,
        pattern: str,
        *,
        glob: str | None = None,
        max_results: int = CODE_SEARCH_MAX_RESULTS,
    ) -> list[SearchHit]:
        if shutil.which("rg") is not None:
            hits = await self._search_ripgrep(root, pattern, glob)
        else:
            hits = await self._search_grep(root, pattern, glob)
        return hits[:max_results]

    async def _search_ripgrep(self, root: Path, pattern: str, glob: str | None) -> list[SearchHit]:
        argv = ["rg", "--json", "--no-messages"]
        if glob is not None:
            argv += ["--glob", glob]
        argv += ["--", pattern]
        result = await self._runner.run(argv, cwd=root, timeout=CODE_SEARCH_TIMEOUT_SECONDS)
        hits: list[SearchHit] = []
        for line in result.stdout.splitlines():
            hit = self._parse_ripgrep_line(line)
            if hit is not None:
                hits.append(hit)
        return hits

    async def _search_grep(self, root: Path, pattern: str, glob: str | None) -> list[SearchHit]:
        argv = ["grep", "-rnI"]
        if glob is not None:
            argv.append(f"--include={glob}")
        argv += ["-e", pattern, "."]
        result = await self._runner.run(argv, cwd=root, timeout=CODE_SEARCH_TIMEOUT_SECONDS)
        hits: list[SearchHit] = []
        for line in result.stdout.splitlines():
            hit = self._parse_grep_line(line)
            if hit is not None:
                hits.append(hit)
        return hits

    @staticmethod
    def _truncate(text: str) -> str:
        stripped = text.rstrip("\n")
        if len(stripped) <= CODE_SEARCH_MAX_LINE_CHARS:
            return stripped
        return stripped[:CODE_SEARCH_MAX_LINE_CHARS] + " …[truncated]"

    @classmethod
    def _parse_ripgrep_line(cls, line: str) -> SearchHit | None:
        if not line.strip():
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict) or event.get("type") != "match":
            return None
        data = event.get("data", {})
        path = data.get("path", {}).get("text")
        line_number = data.get("line_number")
        text = data.get("lines", {}).get("text", "")
        if not isinstance(path, str) or not isinstance(line_number, int):
            return None
        return SearchHit(
            path=path.removeprefix("./"), line=line_number, text=cls._truncate(str(text))
        )

    @classmethod
    def _parse_grep_line(cls, line: str) -> SearchHit | None:
        parts = line.split(":", 2)
        if len(parts) < 3:
            return None
        path, raw_line, text = parts
        try:
            line_number = int(raw_line)
        except ValueError:
            return None
        return SearchHit(path=path.removeprefix("./"), line=line_number, text=cls._truncate(text))
