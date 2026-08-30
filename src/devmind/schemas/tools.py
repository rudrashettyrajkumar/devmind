"""DTOs for the tool framework (E6).

`ToolResult` is what every tool returns — a failed tool is a `ToolResult` with
`is_error=True` and a readable `content`, never a raised exception (the executor
guarantees that). The `*Input` models are the typed argument schemas; the JSON schema
handed to the API is generated from them with `model_json_schema()`, never hand-written,
so validation and the wire contract cannot drift.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.constants import (
    LIST_DIR_MAX_DEPTH,
    SEARCH_CODE_TOOL_MAX_RESULTS,
    TODO_MAX_ITEMS,
)
from devmind.core.enums import SymbolKind, TodoStatus


class ToolResult(BaseModel):
    """One tool's outcome. `metadata` carries structured extras (bytes written, match
    count, …) for events and later phases; it never has to be parsed out of `content`.
    """

    model_config = ConfigDict(frozen=True)

    content: str
    is_error: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


# --- tool input models ---------------------------------------------------------
# Every model forbids unknown keys so the generated schema can carry
# `additionalProperties: false` truthfully.

_STRICT = ConfigDict(extra="forbid", frozen=True)


class ListDirInput(BaseModel):
    model_config = _STRICT
    path: str = Field(default=".", description="Workspace-relative directory to list.")
    depth: int = Field(
        default=1, ge=1, le=LIST_DIR_MAX_DEPTH, description="How many levels deep to descend."
    )


class ReadFileInput(BaseModel):
    model_config = _STRICT
    path: str = Field(description="Workspace-relative file to read.")
    start_line: int | None = Field(
        default=None, ge=1, description="First line to return (1-based, inclusive)."
    )
    end_line: int | None = Field(
        default=None, ge=1, description="Last line to return (1-based, inclusive)."
    )


class SearchCodeInput(BaseModel):
    model_config = _STRICT
    pattern: str = Field(min_length=1, description="Regular expression to search for.")
    glob: str | None = Field(
        default=None, description="Optional path glob to restrict the search, e.g. '*.py'."
    )
    max_results: int = Field(
        default=SEARCH_CODE_TOOL_MAX_RESULTS,
        ge=1,
        le=SEARCH_CODE_TOOL_MAX_RESULTS,
        description="Maximum match lines to return.",
    )


class FindSymbolInput(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, description="Exact symbol name to locate.")
    kind: SymbolKind | None = Field(
        default=None, description="Restrict to 'class' or 'function' if given."
    )


class WriteFileInput(BaseModel):
    model_config = _STRICT
    path: str = Field(description="Workspace-relative file to write (parents are created).")
    content: str = Field(description="Full new file contents.")


class ApplyPatchInput(BaseModel):
    model_config = _STRICT
    path: str = Field(description="Workspace-relative file to patch.")
    old_string: str = Field(
        min_length=1, description="Exact text to replace. Must match once and only once."
    )
    new_string: str = Field(description="Replacement text.")


class RunCommandInput(BaseModel):
    model_config = _STRICT
    argv: tuple[str, ...] = Field(
        min_length=1, description="Command and arguments. Never a shell string."
    )
    timeout_seconds: int | None = Field(
        default=None, gt=0, description="Override the default per-command timeout."
    )


class RunTestsInput(BaseModel):
    model_config = _STRICT
    node_ids: tuple[str, ...] = Field(
        default=(), description="Specific pytest node ids to run; empty runs the suite."
    )
    keyword: str | None = Field(
        default=None, description="Value for pytest's -k expression filter."
    )


class GitDiffInput(BaseModel):
    model_config = _STRICT
    paths: tuple[str, ...] = Field(
        default=(), description="Restrict the diff to these workspace-relative paths."
    )


class TodoItemWrite(BaseModel):
    model_config = _STRICT
    content: str = Field(min_length=1, description="One actionable plan step.")
    status: TodoStatus = Field(
        default=TodoStatus.PENDING, description="Current state of this step."
    )


class TodoWriteInput(BaseModel):
    model_config = _STRICT
    items: tuple[TodoItemWrite, ...] = Field(
        min_length=1,
        max_length=TODO_MAX_ITEMS,
        description="The full plan. Replaces any existing plan.",
    )


class FinishInput(BaseModel):
    model_config = _STRICT
    summary: str = Field(min_length=1, description="What was accomplished in this phase.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Calibrated confidence the phase goal was met (0-1)."
    )
