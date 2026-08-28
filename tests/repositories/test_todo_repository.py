import pytest

from devmind.core.enums import TodoStatus
from devmind.exceptions import RecordNotFoundError
from devmind.repositories import SessionRepository, TodoRepository
from devmind.schemas.session import SessionCreate


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


def test_replace_all_persists_in_order(todo_repo: TodoRepository, session_id: str) -> None:
    items = todo_repo.replace_all(session_id, ["read the code", "write the fix", "run tests"])
    assert [i.content for i in items] == ["read the code", "write the fix", "run tests"]
    assert [i.position for i in items] == [0, 1, 2]
    assert all(i.status is TodoStatus.PENDING for i in items)


def test_replace_all_discards_the_previous_plan(todo_repo: TodoRepository, session_id: str) -> None:
    todo_repo.replace_all(session_id, ["old item"])
    new_items = todo_repo.replace_all(session_id, ["new item one", "new item two"])
    assert [i.content for i in todo_repo.list_for_session(session_id)] == [
        i.content for i in new_items
    ]


def test_update_status(todo_repo: TodoRepository, session_id: str) -> None:
    items = todo_repo.replace_all(session_id, ["do the thing"])
    updated = todo_repo.update_status(items[0].id, TodoStatus.DONE)
    assert updated.status is TodoStatus.DONE


def test_update_status_missing_item_raises(todo_repo: TodoRepository) -> None:
    with pytest.raises(RecordNotFoundError):
        todo_repo.update_status("does-not-exist", TodoStatus.DONE)


def test_list_for_session_orders_by_position(todo_repo: TodoRepository, session_id: str) -> None:
    todo_repo.replace_all(session_id, ["first", "second", "third"])
    contents = [i.content for i in todo_repo.list_for_session(session_id)]
    assert contents == ["first", "second", "third"]
