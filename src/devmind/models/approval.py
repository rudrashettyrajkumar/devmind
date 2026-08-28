"""The human approval record. See docs/01-solution-design.md §9 and §11.

This table is the layer-3 enforcement of the approval gate (SI-3): `PRService`
(E10) re-reads a row here before doing anything remote-capable, rather than
trusting whatever its caller claims.
"""

from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from devmind.core.enums import ApprovalDecision
from devmind.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ApprovalModel(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One approval request/decision for one session.

    `token` is opaque and single-use — `consumed_at` is set exactly once, by
    `PRService` immediately after a PR is opened, and a second attempt to consume it
    is an `ApprovalAlreadyConsumedError` (E9).
    """

    __tablename__ = "approvals"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    token: Mapped[str] = mapped_column(unique=True, index=True)
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        SAEnum(ApprovalDecision, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    reason: Mapped[str | None]
    decided_by: Mapped[str | None]
    decided_at: Mapped[datetime | None]
    consumed_at: Mapped[datetime | None]
