"""The seam that assembles a `SessionWorkbench` for one session (E7-F3).

A justified ABC (Claude.md §4): the production builder stands up a real sandbox
(`SandboxFactory` → Docker or subprocess), installs dependencies, and wires the tool
registry; tests substitute a builder backed by `FakeSandbox`. Two implementations,
one contract — the same pattern as `Sandbox` and `LLMProvider`.
"""

from abc import ABC, abstractmethod

from devmind.schemas.repo import IngestionResult
from devmind.schemas.session import SessionRead
from devmind.services.session_workbench import SessionWorkbench


class WorkbenchBuilder(ABC):
    """Builds the tool surface and sandbox a session's phases run against."""

    @abstractmethod
    async def build(self, session: SessionRead, ingestion: IngestionResult) -> SessionWorkbench:
        """Stand up the sandbox for `ingestion.workspace_path` and return the
        assembled workbench. The caller owns `SessionWorkbench.cleanup()`.
        """
        ...
