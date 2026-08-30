"""`write_file` — a path-guarded full-file write with parent creation and a size cap."""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.constants import WRITE_FILE_MAX_BYTES
from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import ToolResult, WriteFileInput
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Write the full contents of a file inside the workspace, creating parent "
    "directories as needed. Overwrites any existing file. Returns the number of "
    "bytes written. For a small edit to a large file prefer `apply_patch`."
)


class WriteFileTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.WRITE_FILE

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return WriteFileInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, WriteFileInput)
        encoded = payload.content.encode("utf-8")
        if len(encoded) > WRITE_FILE_MAX_BYTES:
            return ToolResult(
                content=(
                    f"refusing to write {len(encoded)} bytes; the limit is "
                    f"{WRITE_FILE_MAX_BYTES}. Split the change or use apply_patch."
                ),
                is_error=True,
            )

        path = ctx.guard.resolve(payload.path)
        if path.is_dir():
            return ToolResult(content=f"{payload.path!r} is a directory", is_error=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return ToolResult(
            content=f"wrote {len(encoded)} bytes to {payload.path}",
            metadata={"bytes_written": len(encoded), "path": payload.path},
        )
