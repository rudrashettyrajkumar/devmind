"""The declarative base and shared column mixins every DevMind model builds on.

SQLAlchemy 2.0 style throughout: `DeclarativeBase`, `Mapped[...]` + `mapped_column`.
`sqlalchemy.orm.Session` may be imported here and in `repositories/` — nowhere else
in the codebase (Claude.md §3; enforced by the standards audit).
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String


def utcnow() -> datetime:
    """The one clock every model's timestamp columns read from."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """The declarative base for every DevMind ORM model."""


class UUIDPrimaryKeyMixin:
    """A string-UUID primary key, generated client-side at insert time."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


class TimestampMixin:
    """`created_at` / `updated_at` for models that are mutated after creation.

    Append-only tables (events, test runs) use `CreatedAtMixin` instead — an
    `updated_at` column on a row nothing ever updates is a column with no purpose.
    """

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CreatedAtMixin:
    """`created_at` only, for append-only, never-updated rows."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
