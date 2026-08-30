"""Local aliases for the E6 tool tests. The real fixtures (`tool_workspace`,
`tool_context`) live in the root conftest so `services/` and `safety/` can use them too.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def workspace(tool_workspace: Path) -> Path:
    """The same directory `tool_context.workspace` points at."""
    return tool_workspace
