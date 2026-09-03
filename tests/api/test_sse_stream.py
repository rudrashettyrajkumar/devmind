"""SSE feed — events in order, `Last-Event-ID` / `?after_sequence=` resume, a
heartbeat on an idle stream, and a clean close on a terminal status (E11-F3).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from devmind.core.database import DatabaseManager
from devmind.core.enums import EventType, SessionStatus
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from devmind.services.event_stream_service import EventStreamService
from tests.api.conftest import SeedFn


def _frames(text: str) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            fields[key] = value
        parsed.append(fields)
    return parsed


def test_stream_emits_events_in_order_then_closes(client: TestClient, seed_session: SeedFn) -> None:
    sid = seed_session(events=3, advance_to=[SessionStatus.FAILED])
    response = client.get(f"/api/v1/sessions/{sid}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _frames(response.text)
    ids = [f["id"] for f in frames]
    # the 3 seeded events plus the STATE_CHANGED from advance_to
    assert ids == ["1", "2", "3", "4"]


def test_stream_resumes_after_a_sequence(client: TestClient, seed_session: SeedFn) -> None:
    sid = seed_session(events=3, advance_to=[SessionStatus.FAILED])
    response = client.get(f"/api/v1/sessions/{sid}/stream", params={"after_sequence": 3})
    assert [f["id"] for f in _frames(response.text)] == ["4"]


def test_stream_resumes_from_the_last_event_id_header(
    client: TestClient, seed_session: SeedFn
) -> None:
    sid = seed_session(events=4, advance_to=[SessionStatus.FAILED])
    response = client.get(f"/api/v1/sessions/{sid}/stream", headers={"Last-Event-ID": "4"})
    assert [f["id"] for f in _frames(response.text)] == ["5"]


def test_unknown_session_is_404_before_the_stream_opens(client: TestClient) -> None:
    assert client.get("/api/v1/sessions/nope/stream").status_code == 404


async def test_heartbeat_on_an_idle_stream(db: DatabaseManager) -> None:
    with db.session_scope() as s:
        sid = (
            SessionRepository(s)
            .create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1))
            .id
        )
        EventRepository(s).append(sid, EventType.STATE_CHANGED, {"i": 0})

    service = EventStreamService(db, poll_interval=0.005, heartbeat_interval=0.005)
    seen: list[str] = []
    agen = service.stream(sid, after_sequence=0)
    try:
        for _ in range(6):
            seen.append(await agen.__anext__())
    finally:
        await agen.aclose()

    assert seen[0].startswith("id: 1")
    assert any(chunk.startswith(":") for chunk in seen), seen  # a heartbeat comment


async def test_stream_terminates_on_terminal_status(db: DatabaseManager) -> None:
    with db.session_scope() as s:
        sid = (
            SessionRepository(s)
            .create(SessionCreate(repo_url="https://github.com/a/b", issue_number=2))
            .id
        )
        EventRepository(s).append(sid, EventType.STATE_CHANGED, {"i": 0})
        EventRepository(s).append(sid, EventType.STATE_CHANGED, {"i": 1})
        SessionRepository(s).update_status(sid, SessionStatus.FAILED)

    service = EventStreamService(db, poll_interval=0.005, heartbeat_interval=10.0)
    chunks = [chunk async for chunk in service.stream(sid)]
    assert [c.split("\n")[0] for c in chunks] == ["id: 1", "id: 2"]
