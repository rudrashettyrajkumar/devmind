"""One test-suite execution. See docs/01-solution-design.md §11 and §8."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from devmind.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class TestRunModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One pytest invocation, baseline or an attempt. Never updated after creation —
    the self-correction loop (E8) reads history from a sequence of these rows, it
    never edits one. `report` holds the full `TestFailureReport` payload as JSON;
    `signature` is denormalized onto its own column because
    `SelfCorrectionController` (E8) queries by it directly.
    """

    __tablename__ = "test_runs"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    attempt: Mapped[int]
    is_baseline: Mapped[bool] = mapped_column(default=False)
    exit_code: Mapped[int]
    passed: Mapped[int]
    failed: Mapped[int]
    errors: Mapped[int]
    signature: Mapped[str | None] = mapped_column(index=True)
    report: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[float]
