"""`GET /sessions/{id}/events` pagination and `GET /sessions/{id}/diff` content type
(E11-F2-T1).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from devmind.api.dependencies import get_session_service
from tests.api.conftest import SeedFn


def test_events_paginate_by_after_sequence(client: TestClient, seed_session: SeedFn) -> None:
    sid = seed_session(events=5)

    first_two = client.get(f"/api/v1/sessions/{sid}/events", params={"limit": 2}).json()
    assert [e["sequence"] for e in first_two] == [1, 2]

    rest = client.get(f"/api/v1/sessions/{sid}/events", params={"after_sequence": 2}).json()
    assert [e["sequence"] for e in rest] == [3, 4, 5]


def test_events_unknown_session_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/sessions/nope/events").status_code == 404


def test_diff_endpoint_is_text_plain(
    app: FastAPI, client: TestClient, seed_session: SeedFn
) -> None:
    sid = seed_session()

    class _StubService:
        async def diff(self, session_id: str) -> str:
            return "diff --git a/x b/x\n+changed\n"

    app.dependency_overrides[get_session_service] = lambda: _StubService()
    response = client.get(f"/api/v1/sessions/{sid}/diff")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "diff --git" in response.text
