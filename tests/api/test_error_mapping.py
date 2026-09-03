"""E11 §"Error mapping": every `DevMindError` subclass reaches the client as an
RFC-7807 body at its declared status. One handler, driven off `exc.http_status`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devmind.api.errors import ErrorHandlerRegistrar
from devmind.exceptions import (
    ApprovalAlreadyConsumedError,
    ApprovalRequiredError,
    BudgetExceededError,
    DevMindError,
    GitHubError,
    InvalidStateTransitionError,
    PathEscapeError,
    RepositoryIngestionError,
    SandboxError,
    SessionNotFoundError,
)


class _UnmappedError(DevMindError):
    """A subclass that does not override http_status — must fall through to 500."""


_CASES = [
    (InvalidStateTransitionError, 409),
    (ApprovalRequiredError, 403),
    (ApprovalAlreadyConsumedError, 409),
    (RepositoryIngestionError, 422),
    (PathEscapeError, 400),
    # E5 set SandboxError to 500 (a sandbox that won't start is server-side); the
    # design-doc table lists 400. The exception class is authoritative.
    (SandboxError, 500),
    (BudgetExceededError, 402),
    (GitHubError, 502),
    (SessionNotFoundError, 404),
    (_UnmappedError, 500),
]


@pytest.fixture(params=_CASES, ids=lambda c: c[0].__name__)
def raising_client(request: pytest.FixtureRequest) -> tuple[TestClient, type[DevMindError], int]:
    exc_type, expected = request.param
    app = FastAPI()
    ErrorHandlerRegistrar().register(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc_type("kaboom", details={"k": "v"})

    return TestClient(app, raise_server_exceptions=False), exc_type, expected


def test_maps_to_status_and_rfc7807_body(
    raising_client: tuple[TestClient, type[DevMindError], int],
) -> None:
    client, exc_type, expected = raising_client
    response = client.get("/boom")

    assert response.status_code == expected
    body = response.json()
    assert body["status"] == expected
    assert body["title"] == exc_type.__name__
    assert body["detail"] == "kaboom"
    assert body["instance"] == "/boom"
    assert body["type"].startswith("/errors/")
    assert body["details"] == {"k": "v"}
