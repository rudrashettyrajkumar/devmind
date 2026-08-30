"""The agent-facing capability seam (E6, docs/01-solution-design.md §6.2).

A justified ABC: the registry iterates a dozen implementations behind one uniform
JSON-schema contract — textbook polymorphism (Claude.md §4). The plumbing bundle a
tool needs at call time is `ToolContext`, which lives in `tools/` (it holds concrete
collaborators, not a port); this module references it only under `TYPE_CHECKING`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel

from devmind.core.enums import ToolName
from devmind.schemas.tools import ToolResult

if TYPE_CHECKING:
    from devmind.tools.tool_context import ToolContext


class Tool(ABC):
    """One agent capability. Stateless — all per-call state arrives in `execute`."""

    @property
    @abstractmethod
    def name(self) -> ToolName:
        """The registry key and the `name` the model calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Model-facing help: when to use this tool and what it returns. Stable —
        it lives in the cached prefix.
        """
        ...

    @property
    @abstractmethod
    def input_model(self) -> type[BaseModel]:
        """The Pydantic model the arguments are validated against and the API schema
        is generated from.
        """
        ...

    @abstractmethod
    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult:
        """Run the tool. Return a `ToolResult` — including for expected failures
        (`is_error=True`). The executor turns any raised exception into an error
        result, but a tool should prefer to return one itself with a useful message.
        """
        ...
