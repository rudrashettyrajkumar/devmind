"""`run_command` — the one narrow, allowlisted shell escape hatch.

No generic `bash` tool exists by design (docs/01-solution-design.md §6.2): dedicated
typed tools plus this. The sandbox enforces the binary allowlist (SI-8) and the
credential-free, network-restricted environment (SI-2); this tool only shapes the
call and the result.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.constants import SANDBOX_COMMAND_TIMEOUT_SECONDS
from devmind.core.enums import ToolName
from devmind.exceptions import SandboxError
from devmind.interfaces.tool import Tool
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.tools import RunCommandInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Run an allowlisted binary in the sandbox. `argv` is a list — never a shell "
    "string; pipes and redirects do not work. Returns exit code, stdout, and stderr. "
    "Only a small set of binaries is permitted; anything else is rejected."
)


class RunCommandTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.RUN_COMMAND

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return RunCommandInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, RunCommandInput)
        command = SandboxCommand(
            argv=payload.argv,
            timeout_seconds=payload.timeout_seconds or SANDBOX_COMMAND_TIMEOUT_SECONDS,
        )
        try:
            result = await ctx.sandbox.run(command)
        except SandboxError as exc:
            return ToolResult(content=exc.message, is_error=True)

        body = (
            f"exit code: {result.exit_code}"
            f"{' (timed out)' if result.timed_out else ''}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
        return ToolResult(
            content=body,
            is_error=not result.succeeded,
            metadata={
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "duration_seconds": result.duration_seconds,
            },
        )
