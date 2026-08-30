"""`run_tests` — a thin shell over pytest in the sandbox.

**This is a seam, not the real implementation.** E8's `TestExecutionService` replaces
the body with structured failure parsing, a `TestRun` record, and baseline handling
(docs/specs/epic-08). E6 only wires the tool so the agent surface is complete: it
builds the pytest argv from `RepoProfile.test_command` and returns the raw output.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.tools import RunTestsInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Run the repository's test suite (pytest) in the sandbox. Pass `node_ids` to run "
    "specific tests or `keyword` for a -k filter; omit both to run everything. "
    "Returns the raw pytest output."
)


class RunTestsTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.RUN_TESTS

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return RunTestsInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, RunTestsInput)
        if not ctx.profile.has_test_suite:
            return ToolResult(content="this repository has no detected test suite", is_error=True)

        base = ctx.profile.test_command or ("python", "-m", "pytest")
        argv: list[str] = [*base]
        if payload.keyword:
            argv += ["-k", payload.keyword]
        argv += list(payload.node_ids)

        result = await ctx.sandbox.run(SandboxCommand(argv=tuple(argv)))
        body = f"{result.stdout}\n{result.stderr}".strip()
        return ToolResult(
            content=body or f"pytest exited {result.exit_code} with no output",
            is_error=not result.succeeded,
            metadata={"exit_code": result.exit_code, "timed_out": result.timed_out},
        )
