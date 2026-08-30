"""The assembled registry: every tool present, schema-valid, and strict."""

from __future__ import annotations

import json

import pytest

from devmind.core.enums import ToolName
from devmind.services.code_search_service import CodeSearchService
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_suite import build_tool_registry


@pytest.fixture
def registry() -> ToolRegistry:
    return build_tool_registry(
        search=CodeSearchService(SubprocessCommandRunner()), indexer=SymbolIndexer()
    )


def test_every_tool_name_is_registered(registry: ToolRegistry) -> None:
    assert set(registry.names()) == set(ToolName)


def test_every_tool_has_a_nonempty_description_and_input_model(registry: ToolRegistry) -> None:
    for tool in registry.all():
        assert tool.description.strip()
        assert isinstance(tool.input_model, type)


def test_api_schemas_are_strict_and_closed(registry: ToolRegistry) -> None:
    schemas = registry.to_api_schemas()
    assert len(schemas) == len(ToolName)
    for schema in schemas:
        assert schema["strict"] is True
        assert schema["input_schema"]["additionalProperties"] is False
        assert schema["name"] in {member.value for member in ToolName}


def test_api_schemas_are_byte_stable(registry: ToolRegistry) -> None:
    assert json.dumps(registry.to_api_schemas()) == json.dumps(registry.to_api_schemas())


def test_read_only_subset_excludes_write_and_exec_tools(registry: ToolRegistry) -> None:
    read_only = registry.subset(
        {ToolName.LIST_DIR, ToolName.READ_FILE, ToolName.SEARCH_CODE, ToolName.FIND_SYMBOL}
    )
    assert not read_only.has("write_file")
    assert not read_only.has("apply_patch")
    assert not read_only.has("run_command")
