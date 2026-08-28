"""The delivered draft PR record. See docs/01-solution-design.md §11.

Created exactly once per session, by `PRService` (E10), and only after that
session's `ApprovalModel` shows a consumed `APPROVED` decision.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from devmind.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class PullRequestModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """The one PR a session ever opens — always as a draft (SI-6)."""

    __tablename__ = "pull_requests"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), unique=True, index=True)
    number: Mapped[int]
    url: Mapped[str]
    branch: Mapped[str]
    head_sha: Mapped[str]
