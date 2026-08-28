"""SQLAlchemy ORM models. Every model must be imported here so `Base.metadata`
picks it up before `DatabaseManager.create_all()` runs — a model defined but never
imported is a table that silently never gets created.
"""

from devmind.models.approval import ApprovalModel
from devmind.models.base import Base
from devmind.models.event import EventModel
from devmind.models.pull_request import PullRequestModel
from devmind.models.session import SessionModel
from devmind.models.test_run import TestRunModel
from devmind.models.todo import TodoItemModel

__all__ = [
    "ApprovalModel",
    "Base",
    "EventModel",
    "PullRequestModel",
    "SessionModel",
    "TestRunModel",
    "TodoItemModel",
]
