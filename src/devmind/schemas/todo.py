"""Request/response DTOs for a session's plan."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from devmind.core.enums import TodoStatus


class TodoItemRead(BaseModel):
    """One step of the plan, as returned in the session state and the approval
    payload (E9, E11).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    position: int
    content: str
    status: TodoStatus
    created_at: datetime
    updated_at: datetime
