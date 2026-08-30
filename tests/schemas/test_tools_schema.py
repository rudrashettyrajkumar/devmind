from __future__ import annotations

import pytest
from pydantic import ValidationError

from devmind.core.constants import LIST_DIR_MAX_DEPTH, SEARCH_CODE_TOOL_MAX_RESULTS, TODO_MAX_ITEMS
from devmind.schemas.tools import (
    ListDirInput,
    RunCommandInput,
    SearchCodeInput,
    TodoItemWrite,
    TodoWriteInput,
    ToolResult,
)


def test_tool_result_defaults_and_frozen() -> None:
    result = ToolResult(content="ok")
    assert result.is_error is False
    assert result.metadata == {}
    with pytest.raises(ValidationError):
        result.content = "changed"


def test_input_models_forbid_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        ListDirInput(path=".", surprise=1)  # type: ignore[call-arg]


def test_list_dir_depth_is_bounded() -> None:
    ListDirInput(depth=LIST_DIR_MAX_DEPTH)
    with pytest.raises(ValidationError):
        ListDirInput(depth=LIST_DIR_MAX_DEPTH + 1)


def test_search_max_results_is_bounded() -> None:
    with pytest.raises(ValidationError):
        SearchCodeInput(pattern="x", max_results=SEARCH_CODE_TOOL_MAX_RESULTS + 1)


def test_run_command_requires_non_empty_argv() -> None:
    with pytest.raises(ValidationError):
        RunCommandInput(argv=())


def test_todo_write_bounds_item_count() -> None:
    with pytest.raises(ValidationError):
        TodoWriteInput(items=())
    too_many = tuple(TodoItemWrite(content=f"s{i}") for i in range(TODO_MAX_ITEMS + 1))
    with pytest.raises(ValidationError):
        TodoWriteInput(items=too_many)
