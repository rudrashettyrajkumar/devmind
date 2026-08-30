"""`read_file` — a line-ranged, line-numbered file read with a hard cap."""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.constants import (
    BINARY_FILE_EXTENSIONS,
    MAX_FILE_READ_LINES,
    READ_FILE_NULL_SCAN_BYTES,
)
from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import ReadFileInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Read a UTF-8 text file inside the workspace. Optionally pass `start_line` and "
    "`end_line` (1-based, inclusive) to read a slice. Output is line-numbered. Large "
    "reads are capped; binary files are rejected with an error."
)


class ReadFileTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.READ_FILE

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return ReadFileInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, ReadFileInput)
        if (
            payload.end_line is not None
            and payload.start_line is not None
            and payload.end_line < payload.start_line
        ):
            return ToolResult(content="end_line must be >= start_line", is_error=True)

        path = ctx.guard.resolve(payload.path)
        if not path.is_file():
            return ToolResult(content=f"{payload.path!r} is not a file", is_error=True)
        if path.suffix.lower() in BINARY_FILE_EXTENSIONS:
            return ToolResult(content=f"{payload.path!r} is a binary file", is_error=True)

        raw = path.read_bytes()
        if b"\x00" in raw[:READ_FILE_NULL_SCAN_BYTES]:
            return ToolResult(
                content=f"{payload.path!r} looks binary (contains NUL bytes)", is_error=True
            )

        lines = raw.decode("utf-8", "replace").splitlines()
        total = len(lines)
        start = (payload.start_line or 1) - 1
        end = payload.end_line if payload.end_line is not None else total
        window = lines[start:end]

        capped = False
        if len(window) > MAX_FILE_READ_LINES:
            window = window[:MAX_FILE_READ_LINES]
            capped = True

        numbered = "\n".join(
            f"{start + offset + 1:6d}  {line}" for offset, line in enumerate(window)
        )
        if capped:
            numbered += f"\n... [truncated after {MAX_FILE_READ_LINES} lines; file has {total}]"
        return ToolResult(
            content=numbered or "(empty selection)",
            metadata={"total_lines": total, "returned_lines": len(window), "truncated": capped},
        )
