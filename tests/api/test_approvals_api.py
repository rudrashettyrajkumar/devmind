"""`/api/v1/sessions/{id}/approval[-request]` — 409 unless AWAITING_APPROVAL,
approve/reject, `decided_by` required, a rejection needs a reason (E11-F2, SI-3/E9).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devmind.api.dependencies import get_session_service
from devmind.core.enums import SessionStatus
from devmind.schemas.approval import (
    ApprovalRequest,
    ChangeSummary,
    SessionMetrics,
    TestEvidence,
)
from tests.api.conftest import SeedFn


@pytest.fixture
def awaiting_session(seed_session: SeedFn) -> str:
    return seed_session(advance_to=[SessionStatus.AWAITING_APPROVAL], create_approval=True)


def test_approve_records_the_decision(client: TestClient, awaiting_session: str) -> None:
    response = client.post(
        f"/api/v1/sessions/{awaiting_session}/approval",
        json={"decision": "approved", "decided_by": "Dana Reviewer"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "approved"
    assert body["decided_by"] == "Dana Reviewer"
    assert "token" not in body  # the token is never exposed over HTTP


def test_reject_requires_a_reason(client: TestClient, awaiting_session: str) -> None:
    bad = client.post(
        f"/api/v1/sessions/{awaiting_session}/approval",
        json={"decision": "rejected", "decided_by": "Dana"},
    )
    assert bad.status_code == 422

    ok = client.post(
        f"/api/v1/sessions/{awaiting_session}/approval",
        json={"decision": "rejected", "decided_by": "Dana", "reason": "not this way"},
    )
    assert ok.status_code == 200
    assert ok.json()["decision"] == "rejected"


def test_decided_by_is_required(client: TestClient, awaiting_session: str) -> None:
    response = client.post(
        f"/api/v1/sessions/{awaiting_session}/approval", json={"decision": "approved"}
    )
    assert response.status_code == 422


def test_approval_request_is_409_unless_awaiting_approval(
    client: TestClient, seed_session: SeedFn
) -> None:
    sid = seed_session()
    response = client.get(f"/api/v1/sessions/{sid}/approval-request")
    assert response.status_code == 409
    assert response.json()["title"] == "InvalidStateTransitionError"


def test_approval_request_returns_what_the_service_builds(
    app: FastAPI, client: TestClient, seed_session: SeedFn
) -> None:
    """Payload assembly is E9's; this only proves the route returns the service's
    output, with the workspace/sandbox wiring stubbed out.
    """
    sid = seed_session(advance_to=[SessionStatus.AWAITING_APPROVAL])
    payload = ApprovalRequest(
        session_id=sid,
        repo_url="https://github.com/a/b",
        issue=None,
        issue_understanding="x",
        plan=(),
        summary=ChangeSummary(markdown="md", issue_understanding="x", risk_notes=("r",)),
        diff="",
        diff_stats=(),
        test_evidence=TestEvidence(),
        risk_notes=("r",),
        warnings=("UNVERIFIED — no test suite found in this repository",),
        metrics=SessionMetrics(
            fix_attempts=0,
            total_steps=0,
            wall_time_seconds=1.0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
        ),
        created_at=datetime.now(UTC),
    )

    class _StubService:
        async def approval_request(self, session_id: str) -> ApprovalRequest:
            return payload

    app.dependency_overrides[get_session_service] = lambda: _StubService()
    response = client.get(f"/api/v1/sessions/{sid}/approval-request")
    assert response.status_code == 200
    assert response.json()["warnings"][0].startswith("UNVERIFIED")
