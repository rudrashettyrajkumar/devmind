"""One item on the agent's plan. See docs/01-solution-design.md §11."""

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from devmind.core.enums import TodoStatus
from devmind.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TodoItemModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single step of the plan `PlannerService` (E7) writes and the agent updates
    as it works. `position` is the item's order within the session's current plan.
    """

    __tablename__ = "todo_items"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    position: Mapped[int]
    content: Mapped[str]
    status: Mapped[TodoStatus] = mapped_column(
        SAEnum(TodoStatus, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        default=TodoStatus.PENDING,
    )
