"""The session aggregate root. See docs/01-solution-design.md §11."""

from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from devmind.core.enums import SandboxBackend, SessionStatus
from devmind.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SessionModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One DevMind run against one issue on one repository.

    `issue_title` / `issue_body` are populated from `gh issue view` during ingestion
    (E4) when `issue_number` is set; when the session was created from free-text
    `issue_description` instead, `issue_body` holds that text directly and
    `issue_title` stays `None` — see `SessionRepository.create()`.
    """

    __tablename__ = "sessions"

    repo_url: Mapped[str]
    issue_number: Mapped[int | None]
    issue_title: Mapped[str | None]
    issue_body: Mapped[str | None]
    base_commit_sha: Mapped[str | None]
    default_branch: Mapped[str | None]
    workspace_path: Mapped[str | None]
    branch_name: Mapped[str | None]
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, native_enum=False, values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.CREATED,
        index=True,
    )
    sandbox_backend: Mapped[SandboxBackend | None] = mapped_column(
        SAEnum(SandboxBackend, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    fix_attempts: Mapped[int] = mapped_column(default=0)
    total_steps: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    has_test_suite: Mapped[bool] = mapped_column(default=True)
    failure_reason: Mapped[str | None]
    completed_at: Mapped[datetime | None]
