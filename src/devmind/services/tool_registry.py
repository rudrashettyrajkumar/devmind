"""`ToolRegistry` — registration, lookup, phase subsetting, and API-schema emission (E6).

`subset()` is how a phase gets a restricted capability set: the investigation phase is
handed a read-only registry, so the agent *cannot* edit before it has understood the
code — a structural property, not a prompt instruction.

`to_api_schemas()` must be byte-stable across calls within a session: the tool block
sits at the front of the cached prefix and any reordering silently destroys the cache.
Keys are sorted; tools are emitted in a fixed order.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from devmind.core.enums import ToolName
from devmind.exceptions import ConfigurationError, ToolExecutionError
from devmind.interfaces.tool import Tool


class ToolRegistry:
    """An ordered, name-unique collection of `Tool`s."""

    def __init__(self) -> None:
        self._tools: dict[ToolName, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ConfigurationError(
                f"tool {tool.name.value!r} is already registered",
                details={"tool": tool.name.value},
            )
        self._tools[tool.name] = tool

    def register_all(self, tools: Sequence[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool:
        try:
            key = ToolName(name)
        except ValueError:
            raise self._unknown(name) from None
        tool = self._tools.get(key)
        if tool is None:
            raise self._unknown(name)
        return tool

    def has(self, name: str) -> bool:
        try:
            return ToolName(name) in self._tools
        except ValueError:
            return False

    def all(self) -> Sequence[Tool]:
        return tuple(self._ordered())

    def names(self) -> tuple[ToolName, ...]:
        return tuple(tool.name for tool in self._ordered())

    def subset(self, names: Collection[ToolName]) -> ToolRegistry:
        """A new registry containing only `names` (those actually registered)."""
        wanted = set(names)
        child = ToolRegistry()
        child.register_all([tool for tool in self._ordered() if tool.name in wanted])
        return child

    def to_api_schemas(self) -> list[dict[str, object]]:
        """One entry per tool: `name`, `description`, `input_schema`
        (`additionalProperties: false`, full `required`), and `strict: true`.
        Deterministic and byte-stable within a session.
        """
        schemas: list[dict[str, object]] = []
        for tool in self._ordered():
            input_schema = tool.input_model.model_json_schema()
            input_schema.setdefault("additionalProperties", False)
            schemas.append(
                {
                    "name": tool.name.value,
                    "description": tool.description,
                    "input_schema": _sorted(input_schema),
                    "strict": True,
                }
            )
        return schemas

    def _ordered(self) -> list[Tool]:
        # Enum declaration order — fixed for the life of the process, so the schema
        # block never reorders between calls.
        return [self._tools[name] for name in ToolName if name in self._tools]

    @staticmethod
    def _unknown(name: str) -> ToolExecutionError:
        valid = ", ".join(member.value for member in ToolName)
        return ToolExecutionError(
            f"unknown tool {name!r}; valid tools are: {valid}",
            details={"requested": name},
        )


def _sorted(value: object) -> object:
    """Recursively sort dict keys so `json.dumps` output is order-independent."""
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value
