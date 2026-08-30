"""`ToolContext` — the plumbing bundle every tool is handed at call time (E6).

It holds concrete collaborators (a guard, a sandbox, two repositories), so it lives
here in `tools/` rather than in `interfaces/` — a port it is not. The `Tool` ABC
references it only under `TYPE_CHECKING`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devmind.interfaces.sandbox import Sandbox
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.todo_repository import TodoRepository
from devmind.schemas.repo import RepoProfile
from devmind.services.workspace_path_guard import WorkspacePathGuard


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may need to do its job, assembled once per session."""

    session_id: str
    workspace: Path
    guard: WorkspacePathGuard
    sandbox: Sandbox
    profile: RepoProfile
    todos: TodoRepository
    events: EventRepository
