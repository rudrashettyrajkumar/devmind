"""`SessionWorkbench` — the per-session bundle the agent loop works through (E7-F3).

One session, one workspace, one sandbox lifecycle. The orchestrator asks a
`WorkbenchBuilder` for this, runs every phase against it, and calls `cleanup()` in a
`finally` — a crashed session must never leak a container.
"""

from __future__ import annotations

from dataclasses import dataclass

from devmind.interfaces.sandbox import Sandbox
from devmind.services.tool_registry import ToolRegistry
from devmind.tools.tool_context import ToolContext


@dataclass
class SessionWorkbench:
    """The assembled hands for one session: the full tool registry, the call-time
    `ToolContext`, and the sandbox whose lifecycle this object owns.
    """

    tool_context: ToolContext
    registry: ToolRegistry
    sandbox: Sandbox

    async def cleanup(self) -> None:
        """Release the sandbox. Safe to call once, on any exit path."""
        await self.sandbox.teardown()
