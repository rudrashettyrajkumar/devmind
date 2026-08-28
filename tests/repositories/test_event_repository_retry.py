"""A focused unit test for the IntegrityError-retry path itself — the concurrency
test proves the end-to-end guarantee, this proves the specific mechanism.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from devmind.core.enums import EventType
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.session_repository import SessionRepository
from devmind.schemas.session import SessionCreate


def test_retries_once_on_sequence_collision_then_succeeds(
    session_repo: SessionRepository, event_repo: EventRepository
) -> None:
    session_id = session_repo.create(
        SessionCreate(repo_url="https://github.com/a/b", issue_number=1)
    ).id

    real_commit = event_repo._session.commit
    call_count = 0

    def _fail_once_then_commit() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise IntegrityError("insert", {}, Exception("unique constraint"))
        real_commit()

    # Patched only for the duration of this `with` block — restored automatically,
    # so `db_session`'s own fixture-teardown commit (in `DatabaseManager.session_scope`)
    # never touches the mock.
    with patch.object(event_repo._session, "commit", side_effect=_fail_once_then_commit):
        event = event_repo.append(session_id, EventType.LLM_CALL, {})

    assert call_count == 2
    assert event.sequence == 1


def test_raises_after_exhausting_retries(
    session_repo: SessionRepository, event_repo: EventRepository
) -> None:
    session_id = session_repo.create(
        SessionCreate(repo_url="https://github.com/a/b", issue_number=1)
    ).id

    def _always_fail() -> None:
        raise IntegrityError("insert", {}, Exception("unique constraint"))

    with (
        patch.object(event_repo._session, "commit", side_effect=_always_fail),
        pytest.raises(IntegrityError),
    ):
        event_repo.append(session_id, EventType.LLM_CALL, {})
