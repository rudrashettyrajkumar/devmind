"""SI-1: the agent can never push, open a PR, merge, or contact a remote.

This is the epic's whole point. The registry contains no remote-capable tool, so the
agent has no route to a remote no matter what it decides. A regression here is a
broken invariant — fix the code, never the test.
"""

from __future__ import annotations

import inspect

import pytest

from devmind.services.code_search_service import CodeSearchService
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_suite import build_tool_registry

_FORBIDDEN_NAME_PARTS = {
    "push",
    "pr",
    "pull",
    "remote",
    "fetch",
    "clone",
    "curl",
    "wget",
    "http",
    "upload",
    "publish",
}
_FORBIDDEN_SOURCE_FRAGMENTS = (
    "git push",
    "gh pr",
    "gh api",
    "urlopen",
    "requests.",
    "httpx.",
    "socket.socket",
    "urllib.request",
)


@pytest.fixture
def registry() -> ToolRegistry:
    return build_tool_registry(
        search=CodeSearchService(SubprocessCommandRunner()), indexer=SymbolIndexer()
    )


def test_si1_no_tool_name_implies_a_remote_capability(registry: ToolRegistry) -> None:
    for tool in registry.all():
        parts = set(tool.name.value.split("_"))
        assert not (_FORBIDDEN_NAME_PARTS & parts), tool.name.value


def test_si1_no_tool_source_reaches_the_network(registry: ToolRegistry) -> None:
    for tool in registry.all():
        source = inspect.getsource(type(tool)).lower()
        for fragment in _FORBIDDEN_SOURCE_FRAGMENTS:
            assert fragment not in source, f"{type(tool).__name__} references {fragment!r}"


def test_si1_registry_has_exactly_the_intended_tools(registry: ToolRegistry) -> None:
    assert {name.value for name in registry.names()} == {
        "list_dir",
        "read_file",
        "search_code",
        "find_symbol",
        "write_file",
        "apply_patch",
        "run_command",
        "run_tests",
        "git_diff",
        "todo_write",
        "finish",
    }
