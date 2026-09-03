"""`POST/GET /api/v1/sessions` — create returns 202 + id and schedules a run; get;
list with a status filter; 404 on an unknown id (E11-F2-T1).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from devmind.core.enums import SessionStatus
from tests.api.conftest import FakeSessionRunner, SeedFn


def test_create_returns_202_and_schedules_the_run(
    client: TestClient, runner_fake: FakeSessionRunner
) -> None:
    response = client.post(
        "/api/v1/sessions",
        json={"repo_url": "https://github.com/acme/widget", "issue_number": 42},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "created"
    assert body["repo_url"] == "https://github.com/acme/widget"
    assert runner_fake.launched == [body["id"]]


def test_create_rejects_a_body_with_no_issue_input(client: TestClient) -> None:
    response = client.post("/api/v1/sessions", json={"repo_url": "https://github.com/a/b"})
    assert response.status_code == 422


def test_get_returns_the_session(client: TestClient, seed_session: SeedFn) -> None:
    sid = seed_session(issue_description="bug")
    got = client.get(f"/api/v1/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["id"] == sid


def test_get_unknown_id_is_404_rfc7807(client: TestClient) -> None:
    response = client.get("/api/v1/sessions/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "SessionNotFoundError"


def test_list_filters_by_status(client: TestClient, seed_session: SeedFn) -> None:
    awaiting = seed_session(issue_number=1, advance_to=[SessionStatus.AWAITING_APPROVAL])
    seed_session(issue_number=2)

    all_rows = client.get("/api/v1/sessions").json()
    assert len(all_rows) == 2

    filtered = client.get("/api/v1/sessions", params={"status": "awaiting_approval"}).json()
    assert [row["id"] for row in filtered] == [awaiting]


def test_list_rejects_an_oversized_limit(client: TestClient) -> None:
    assert client.get("/api/v1/sessions", params={"limit": 9999}).status_code == 422
