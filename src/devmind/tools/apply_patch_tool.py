"""`apply_patch` — exact-match string replacement that fails loudly on ambiguity.

Silently patching the first of three matches is how an agent corrupts a file in a way
nobody notices until review. Zero matches and more-than-one matches are both errors,
and each message tells the model exactly how to succeed next time.
"""

from __future__ import annotations

from pydantic import BaseModel

from devmind.core.constants import (
    APPLY_PATCH_ANCHOR_SHRINK,
    APPLY_PATCH_CONTEXT_CHARS,
    APPLY_PATCH_MIN_ANCHOR_CHARS,
)
from devmind.core.enums import ToolName
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import ApplyPatchInput, ToolResult
from devmind.tools.tool_context import ToolContext

_DESCRIPTION = (
    "Replace an exact block of text in a workspace file. `old_string` must appear "
    "exactly once — include enough surrounding lines to make it unique. On zero or "
    "multiple matches the tool makes no change and tells you what to adjust."
)


class ApplyPatchTool(Tool):
    @property
    def name(self) -> ToolName:
        return ToolName.APPLY_PATCH

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_model(self) -> type[BaseModel]:
        return ApplyPatchInput

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(payload, ApplyPatchInput)
        path = ctx.guard.resolve(payload.path)
        if not path.is_file():
            return ToolResult(content=f"{payload.path!r} is not a file", is_error=True)

        text = path.read_text(encoding="utf-8", errors="replace")
        count = text.count(payload.old_string)

        if count == 0:
            return ToolResult(content=self._not_found_message(payload, text), is_error=True)
        if count > 1:
            return ToolResult(
                content=(
                    f"`old_string` matched {count} times in {payload.path}. Add more "
                    "surrounding context so it identifies exactly one location."
                ),
                is_error=True,
            )

        path.write_text(text.replace(payload.old_string, payload.new_string, 1), encoding="utf-8")
        return ToolResult(
            content=f"applied patch to {payload.path}",
            metadata={"path": payload.path, "matches": 1},
        )

    @staticmethod
    def _not_found_message(payload: ApplyPatchInput, text: str) -> str:
        anchor = next(
            (line.strip() for line in payload.old_string.splitlines() if line.strip()), ""
        )
        base = f"`old_string` was not found in {payload.path}."
        if not anchor:
            return base
        # Try the whole first line, then progressively shorter prefixes of it, so a
        # near-miss still points the model at the right region.
        position = -1
        probe = anchor
        while len(probe) >= APPLY_PATCH_MIN_ANCHOR_CHARS:
            position = text.find(probe)
            if position != -1:
                anchor = probe
                break
            probe = probe[: int(len(probe) * APPLY_PATCH_ANCHOR_SHRINK)]
        if position == -1:
            return f"{base} No text resembling {anchor!r} is present either."
        window = text[
            max(0, position - APPLY_PATCH_CONTEXT_CHARS) : position
            + len(anchor)
            + APPLY_PATCH_CONTEXT_CHARS
        ]
        return (
            f"{base} The closest text is around a line matching {anchor!r}:\n"
            f"---\n{window}\n---\n"
            "Copy `old_string` verbatim from there, including whitespace."
        )
