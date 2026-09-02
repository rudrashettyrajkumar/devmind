"""`run_tests` — a thin shell over pytest in the sandbox, for the agent's own
iteration *during* the editing phase.

The authoritative test loop — structured `TestFailureReport` parsing, a persisted
`TestRunModel` per attempt, baseline subtraction, and the RETRY / EXHAUSTED verdict —
is `TestExecutionService` + `SelfCorrectionController`, driven by `SessionOrchestrator`
in the TESTING phase (E8). This tool stays deliberately raw: it builds the pytest
argv from `RepoProfile.test_command` and hands back the output verbatim, with no row
and no attempt number, so an exploratory run the agent makes mid-edit never pollutes
that attempt accounting.
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
