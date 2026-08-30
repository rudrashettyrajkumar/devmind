"""Shared fixtures for the DevMind test suite.

Only fixtures genuinely shared across layers belong here — a fixture used by one
test module lives in that module instead. See the `devmind-testing` skill.
"""

import os

# `devmind.main` builds `app = ApplicationFactory().create()` at import time so
# `uvicorn devmind.main:app` works with zero code — but that means importing the
# module (e.g. `from devmind.main import ApplicationFactory`, as test_health.py
# does) resolves Settings() too, before any test gets a chance to inject its own.
# Setting a harmless placeholder here, before collection imports anything, keeps
# that resolvable without weakening Settings' real "fail fast with no key" behavior
# — test_config.py's `test_missing_anthropic_api_key_raises` still constructs
# Settings() directly and bypasses this.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-conftest-placeholder")

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.config import Settings
from devmind.core.database import DatabaseManager
from devmind.repositories import (
    ApprovalRepository,
    EventRepository,
    PullRequestRepository,
    SessionRepository,
    TestRunRepository,
    TodoRepository,
)
from devmind.schemas.session import SessionCreate

if TYPE_CHECKING:
    from devmind.tools.tool_context import ToolContext


@pytest.fixture
def settings() -> Settings:
    """A minimally valid `Settings` instance — no `.env` file, no real credentials."""
    return Settings(anthropic_api_key="sk-ant-test-key-not-real")  # type: ignore[call-arg]


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """A file-backed (not `:memory:`) SQLite database — deliberately, so tests that
    exercise genuine multi-connection concurrency (e.g. the event-sequence race test)
    get real separate connections rather than one connection's worth of isolation.
    """
    manager = DatabaseManager(f"sqlite:///{tmp_path}/test.db")
    manager.create_all()
    return manager


@pytest.fixture
def db_session(db: DatabaseManager) -> Iterator[SQLAlchemySession]:
    """One ORM session, open for the duration of a test, committed and closed after."""
    with db.session_scope() as session:
        yield session


@pytest.fixture
def session_repo(db_session: SQLAlchemySession) -> SessionRepository:
    return SessionRepository(db_session)


@pytest.fixture
def event_repo(db_session: SQLAlchemySession) -> EventRepository:
    return EventRepository(db_session)


@pytest.fixture
def todo_repo(db_session: SQLAlchemySession) -> TodoRepository:
    return TodoRepository(db_session)


@pytest.fixture
def test_run_repo(db_session: SQLAlchemySession) -> TestRunRepository:
    return TestRunRepository(db_session)


@pytest.fixture
def approval_repo(db_session: SQLAlchemySession) -> ApprovalRepository:
    return ApprovalRepository(db_session)


@pytest.fixture
def pull_request_repo(db_session: SQLAlchemySession) -> PullRequestRepository:
    return PullRequestRepository(db_session)


@pytest.fixture
def session_create() -> SessionCreate:
    """A minimally valid `SessionCreate` — an issue number, not free text."""
    return SessionCreate(repo_url="https://github.com/example/repo", issue_number=42)


# --- Tool-framework fixtures (E6), shared across tools/ services/ safety/ -----


@pytest.fixture
def tool_workspace(tmp_path: Path) -> Path:
    """A small on-disk workspace: a `src/pkg` package, a README, and a gitignored file."""
    ws = tmp_path / "ws"
    (ws / "src" / "pkg").mkdir(parents=True)
    (ws / "src" / "pkg" / "__init__.py").write_text("")
    (ws / "src" / "pkg" / "calc.py").write_text(
        "class Calculator:\n    def add(self, a, b):\n        return a - b\n"
    )
    (ws / "README.md").write_text("# sample\n\nsearch anchor here\n")
    (ws / ".gitignore").write_text("*.log\n")
    (ws / "debug.log").write_text("ignored\n")
    return ws


@pytest.fixture
def tool_context(db_session: SQLAlchemySession, tool_workspace: Path) -> "ToolContext":
    """An assembled `ToolContext` backed by in-memory repositories and a `FakeSandbox`."""
    from devmind.schemas.repo import RepoProfile
    from devmind.services.workspace_path_guard import WorkspacePathGuard
    from devmind.tools.tool_context import ToolContext as _ToolContext
    from tests.fakes.fake_sandbox import FakeSandbox

    session = SessionRepository(db_session).create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="fix add")
    )
    return _ToolContext(
        session_id=session.id,
        workspace=tool_workspace,
        guard=WorkspacePathGuard(tool_workspace),
        sandbox=FakeSandbox(),
        profile=RepoProfile(
            language="python", test_command=("python", "-m", "pytest"), has_test_suite=True
        ),
        todos=TodoRepository(db_session),
        events=EventRepository(db_session),
    )
