"""`git_diff` — the working-tree diff, run in the sandbox and capped."""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.constants import MAX_DIFF_CHARS
from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.tools import GitDiffInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Show the unstaged changes in the workspace as a unified diff. Optionally pass "
    "`paths` to limit it. Use it to review what you have changed so far."
)


class GitDiffTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.GIT_DIFF

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return GitDiffInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, GitDiffInput)
        argv = ["git", "diff"]
        if payload.paths:
            # Route each pathspec through the workspace guard (SI-5) rather than
            # trusting git's own containment; a `..` or absolute path raises
            # PathEscapeError, which the executor turns into an is_error result.
            relative = [
                ctx.guard.resolve(path).relative_to(ctx.guard.root).as_posix()
                for path in payload.paths
            ]
            argv += ["--", *relative]

        result = await ctx.sandbox.run(SandboxCommand(argv=tuple(argv)))
        if not result.succeeded and result.stderr:
            return ToolResult(content=result.stderr.strip(), is_error=True)

        diff = result.stdout
        truncated = len(diff) > MAX_DIFF_CHARS
        if truncated:
            diff = diff[:MAX_DIFF_CHARS] + f"\n... [diff truncated at {MAX_DIFF_CHARS} chars]"
        return ToolResult(
            content=diff or "(no changes)",
            metadata={"truncated": truncated, "empty": not result.stdout},
        )
