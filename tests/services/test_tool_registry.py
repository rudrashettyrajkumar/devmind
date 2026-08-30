from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.exceptions import ConfigurationError, ToolExecutionError
from devmind.interfaces.tool import Tool
from devmind.schemas.tools import FinishInput, ListDirInput, ToolResult
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_context import ToolContext


class _Stub(Tool):
    def __init__(self, name: ToolName, model: type[BaseModel] = ListDirInput) -> None:
        self._name = name
        self._model = model

    @property
    def name(self) -> ToolName:
        return self._name

    @property
    def description(self) -> str:
        return f"stub {self._name.value}"

    @property
    def input_model(self) -> type[BaseModel]:
        return self._model

    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        return ToolResult(content="ok")


def test_register_and_get() -> None:
    reg = ToolRegistry()
    tool = _Stub(ToolName.LIST_DIR)
    reg.register(tool)
    assert reg.get("list_dir") is tool
    assert reg.has("list_dir")


def test_duplicate_name_raises_configuration_error() -> None:
    reg = ToolRegistry()
    reg.register(_Stub(ToolName.LIST_DIR))
    with pytest.raises(ConfigurationError):
        reg.register(_Stub(ToolName.LIST_DIR))


def test_get_unknown_name_raises_with_the_valid_list() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolExecutionError) as excinfo:
        reg.get("frobnicate")
    assert "list_dir" in str(excinfo.value)


def test_subset_keeps_only_named_tools() -> None:
    reg = ToolRegistry()
    reg.register_all(
        [_Stub(ToolName.LIST_DIR), _Stub(ToolName.READ_FILE), _Stub(ToolName.WRITE_FILE)]
    )
    read_only = reg.subset({ToolName.LIST_DIR, ToolName.READ_FILE})
    assert set(read_only.names()) == {ToolName.LIST_DIR, ToolName.READ_FILE}
    assert not read_only.has("write_file")


def test_ordering_follows_the_enum_not_registration_order() -> None:
    reg = ToolRegistry()
    reg.register_all([_Stub(ToolName.FINISH, FinishInput), _Stub(ToolName.LIST_DIR)])
    assert reg.names() == (ToolName.LIST_DIR, ToolName.FINISH)


def test_to_api_schemas_is_byte_stable_across_calls() -> None:
    reg = ToolRegistry()
    reg.register_all([_Stub(ToolName.LIST_DIR), _Stub(ToolName.FINISH, FinishInput)])
    first = json.dumps(reg.to_api_schemas())
    second = json.dumps(reg.to_api_schemas())
    assert first == second


def test_to_api_schemas_shape() -> None:
    reg = ToolRegistry()
    reg.register(_Stub(ToolName.LIST_DIR))
    (schema,) = reg.to_api_schemas()
    assert schema["name"] == "list_dir"
    assert schema["strict"] is True
    assert schema["input_schema"]["additionalProperties"] is False
    assert "description" in schema
