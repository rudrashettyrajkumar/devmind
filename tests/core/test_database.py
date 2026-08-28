from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from devmind.core.database import DatabaseManager
from devmind.core.enums import EventType
from devmind.models.session import SessionModel


def test_create_all_is_idempotent(tmp_path: Path) -> None:
    manager = DatabaseManager(f"sqlite:///{tmp_path}/idempotent.db")
    manager.create_all()
    manager.create_all()  # must not raise


def test_session_scope_commits_on_success(tmp_path: Path) -> None:
    manager = DatabaseManager(f"sqlite:///{tmp_path}/commit.db")
    manager.create_all()

    with manager.session_scope() as session:
        session.add(SessionModel(repo_url="https://github.com/a/b", issue_number=1))

    with manager.session_scope() as verify:
        assert verify.query(SessionModel).count() == 1


def test_session_scope_rolls_back_on_exception(tmp_path: Path) -> None:
    manager = DatabaseManager(f"sqlite:///{tmp_path}/rollback.db")
    manager.create_all()

    with pytest.raises(ValueError, match="boom"), manager.session_scope() as session:
        session.add(SessionModel(repo_url="https://github.com/a/b", issue_number=1))
        raise ValueError("boom")

    with manager.session_scope() as verify:
        assert verify.query(SessionModel).count() == 0


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    manager = DatabaseManager(f"sqlite:///{tmp_path}/fk.db")
    manager.create_all()

    from devmind.models.event import EventModel

    with pytest.raises(IntegrityError), manager.session_scope() as session:
        session.add(
            EventModel(
                session_id="no-such-session", sequence=1, event_type=EventType.SESSION_CREATED
            )
        )
