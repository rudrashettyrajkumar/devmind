"""A client disconnect stops the stream cleanly — the generator handles the close,
and because every poll is its own `session_scope()` there is no `Session` to leak
(E11-F3, "test_sse_disconnect").
"""

from __future__ import annotations

import asyncio
import contextlib

from devmind.core.database import DatabaseManager
from devmind.core.enums import EventType
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from devmind.services.event_stream_service import EventStreamService


def _seed(db: DatabaseManager, issue: int) -> str:
    with db.session_scope() as s:
        sid = (
            SessionRepository(s)
            .create(SessionCreate(repo_url="https://github.com/a/b", issue_number=issue))
            .id
        )
        EventRepository(s).append(sid, EventType.STATE_CHANGED, {"i": 0})
        return sid


async def test_aclose_midstream_raises_nothing_and_leaves_the_db_usable(
    db: DatabaseManager,
) -> None:
    sid = _seed(db, 1)
    service = EventStreamService(db, poll_interval=0.005, heartbeat_interval=10.0)
    agen = service.stream(sid, after_sequence=0)  # session not terminal → would run forever

    first = await agen.__anext__()
    assert first.startswith("id: 1")

    await agen.aclose()  # the client went away; must not raise

    with db.session_scope() as fresh:  # nothing left checked out
        assert SessionRepository(fresh).get_by_id(sid) is not None


async def test_cancelled_error_propagates_without_a_leak(db: DatabaseManager) -> None:
    sid = _seed(db, 2)
    service = EventStreamService(db, poll_interval=10.0, heartbeat_interval=10.0)

    async def consume() -> None:
        async for _ in service.stream(sid):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()

    with db.session_scope() as fresh:
        assert SessionRepository(fresh).get_by_id(sid) is not None
