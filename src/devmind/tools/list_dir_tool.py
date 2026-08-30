"""`list_dir` — a gitignore-aware, depth- and count-capped directory listing."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from devmind.core.constants import LIST_DIR_MAX_ENTRIES
from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import ListDirInput, ToolResult
from devmind.services.gitignore_filter import GitignoreFilter
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "List the contents of a directory inside the workspace, up to `depth` levels "
    "deep. Respects .gitignore and skips vendored/build directories. Returns an "
    "indented tree of relative paths. Use it to orient before reading files."
)


class ListDirTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.LIST_DIR

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return ListDirInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, ListDirInput)
        root = ctx.guard.resolve(payload.path)
        if not root.is_dir():
            return ToolResult(content=f"{payload.path!r} is not a directory", is_error=True)

        gitignore = GitignoreFilter.for_root(ctx.workspace)
        lines: list[str] = []
        truncated = self._walk(root, ctx.workspace, gitignore, payload.depth, 0, lines)
        body = "\n".join(lines) if lines else "(empty)"
        if truncated:
            body += f"\n... [listing truncated at {LIST_DIR_MAX_ENTRIES} entries]"
        return ToolResult(content=body, metadata={"entries": len(lines), "truncated": truncated})

    def _walk(
        self,
        directory: Path,
        workspace: Path,
        gitignore: GitignoreFilter,
        max_depth: int,
        depth: int,
        out: list[str],
    ) -> bool:
        if depth >= max_depth:
            return False
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                continue
            rel = entry.relative_to(workspace)
            is_dir = entry.is_dir()
            if gitignore.ignores(rel, is_dir=is_dir):
                continue
            if len(out) >= LIST_DIR_MAX_ENTRIES:
                return True
            out.append(f"{'  ' * depth}{entry.name}{'/' if is_dir else ''}")
            if is_dir and self._walk(entry, workspace, gitignore, max_depth, depth + 1, out):
                return True
        return False
