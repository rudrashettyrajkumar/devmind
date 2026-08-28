"""Proves `EventRepository.append()`'s sequence allocation is race-safe.

Each worker thread opens its own `DatabaseManager.session_scope()` — SQLAlchemy
`Session` objects are not shareable across threads — and appends once to the same
session's event log. If the SELECT-MAX-then-INSERT allocation in `append()` were not
backstopped by the unique constraint + retry, two threads could compute the same
"next sequence" and either collide (an unhandled `IntegrityError`) or silently
duplicate a sequence number.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from devmind.core.database import DatabaseManager
from devmind.core.enums import EventType
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate

_WORKER_COUNT = 50


def test_concurrent_appends_produce_a_gap_free_unique_sequence(db: DatabaseManager) -> None:
    with db.session_scope() as setup_session:
        session_id = (
            SessionRepository(setup_session)
            .create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1))
            .id
        )

    def _append_one(worker_index: int) -> int:
        with db.session_scope() as worker_session:
            event = EventRepository(worker_session).append(
                session_id, EventType.LLM_CALL, {"worker": worker_index}
            )
            return event.sequence

    with ThreadPoolExecutor(max_workers=_WORKER_COUNT) as executor:
        futures = [executor.submit(_append_one, i) for i in range(_WORKER_COUNT)]
        sequences = [future.result() for future in as_completed(futures)]

    assert sorted(sequences) == list(range(1, _WORKER_COUNT + 1))

    with db.session_scope() as verify_session:
        persisted = EventRepository(verify_session).list_since(session_id, limit=_WORKER_COUNT + 1)
    assert [e.sequence for e in persisted] == list(range(1, _WORKER_COUNT + 1))
