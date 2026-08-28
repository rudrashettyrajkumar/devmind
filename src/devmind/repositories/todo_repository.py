"""Data access for a session's plan. `PlannerService` and the `todo_write` tool (E7,
E6) are the callers; this repository only persists what it's told.
"""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from devmind.core.enums import TodoStatus
from devmind.exceptions import RecordNotFoundError
from devmind.models.todo import TodoItemModel


class TodoRepository:
    """CRUD for `TodoItemModel`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_all(self, session_id: str, contents: Sequence[str]) -> list[TodoItemModel]:
        """Replaces the entire plan: deletes every existing item for this session and
        inserts `contents` fresh, in order, all `PENDING`. This is what `todo_write`
        (E6) calls — the plan is always written as a whole, never patched item by item.
        """
        self._session.execute(delete(TodoItemModel).where(TodoItemModel.session_id == session_id))
        items = [
            TodoItemModel(session_id=session_id, position=position, content=content)
            for position, content in enumerate(contents)
        ]
        self._session.add_all(items)
        self._session.commit()
        for item in items:
            self._session.refresh(item)
        return items

    def update_status(self, todo_id: str, status: TodoStatus) -> TodoItemModel:
        model = self._session.get(TodoItemModel, todo_id)
        if model is None:
            raise RecordNotFoundError(
                f"todo item {todo_id} not found", details={"todo_id": todo_id}
            )
        model.status = status
        self._session.commit()
        self._session.refresh(model)
        return model

    def list_for_session(self, session_id: str) -> list[TodoItemModel]:
        stmt = (
            select(TodoItemModel)
            .where(TodoItemModel.session_id == session_id)
            .order_by(TodoItemModel.position)
        )
        return list(self._session.execute(stmt).scalars().all())
