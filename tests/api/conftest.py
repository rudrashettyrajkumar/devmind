"""Fixtures for the E11 API tests.

Every test builds the real app over a file-backed test database, then overrides the
one dependency that would otherwise start work — `get_session_runner` — with a fake
that only records the launch. No API test starts a real session run (spec §Testing).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devmind.api.dependencies import get_session_runner
from devmind.core.config import Settings
from devmind.core.database import DatabaseManager
from devmind.core.enums import EventType, SandboxBackend, SessionStatus
from devmind.main import ApplicationFactory
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate


class FakeSessionRunner:
    """Stands in for `SessionRunner` — records the ids it was asked to launch."""

    def __init__(self) -> None:
        self.launched: list[str] = []

    async def launch(self, session_id: str) -> None:
        self.launched.append(session_id)


@pytest.fixture
def api_settings() -> Settings:
    return Settings(
        anthropic_api_key="sk-ant-test-key",
        sandbox_backend=SandboxBackend.SUBPROCESS,  # skip the docker probe in lifespan
    )  # type: ignore[call-arg]


@pytest.fixture
def runner_fake() -> FakeSessionRunner:
    return FakeSessionRunner()


@pytest.fixture
def app(api_settings: Settings, db: DatabaseManager, runner_fake: FakeSessionRunner) -> FastAPI:
    application = ApplicationFactory(api_settings, database=db).create()
    application.dependency_overrides[get_session_runner] = lambda: runner_fake
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


SeedFn = Callable[..., str]


@pytest.fixture
def seed_session(db: DatabaseManager) -> SeedFn:
    """Create a session (optionally advanced through states and given events) in its
    own short-lived scope, so the API request's transaction is never blocked by a
    still-open test transaction on the same SQLite file.
    """

    def _seed(
        *,
        repo_url: str = "https://github.com/acme/widget",
        issue_number: int | None = 1,
        issue_description: str | None = None,
        advance_to: Sequence[SessionStatus] = (),
        events: int = 0,
        create_approval: bool = False,
    ) -> str:
        with db.session_scope() as db_session:
            sessions = SessionRepository(db_session)
            log = EventRepository(db_session)
            model = sessions.create(
                SessionCreate(
                    repo_url=repo_url,
                    issue_number=issue_number if issue_description is None else None,
                    issue_description=issue_description,
                )
            )
            for target in advance_to:
                sessions.update_status(model.id, target)
                log.append(model.id, EventType.STATE_CHANGED, {"to": target.value})
            for i in range(events):
                log.append(model.id, EventType.STATE_CHANGED, {"i": i})
            if create_approval:
                import secrets

                from devmind.repositories import ApprovalRepository

                ApprovalRepository(db_session).create(model.id, token=secrets.token_urlsafe(16))
            return model.id

    return _seed
