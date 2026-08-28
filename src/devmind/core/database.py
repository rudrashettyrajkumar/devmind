"""The one place `DatabaseManager` lives.

This module and `repositories/` are the only places `sqlalchemy.orm.Session` may be
imported anywhere in this codebase (Claude.md §3) — services and the API layer take a
repository, never a `Session`, through their constructor.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from devmind.models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Owns the engine and hands out sessions through `session_scope()`.

    No Alembic in v1 — `create_all()` is right for a single-process app with no
    production data yet (Claude.md §9); migrations are a follow-up once there is a
    schema to migrate.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        connect_args: dict[str, object] = {}
        if database_url.startswith("sqlite"):
            # A pooled SQLite engine hands connections to whichever thread checks
            # them out next, not necessarily the thread that opened them — without
            # this, a second thread reusing a pooled connection raises
            # ProgrammingError. `timeout` gives SQLite's own busy-wait a chance to
            # resolve write-lock contention before raising OperationalError.
            connect_args = {"check_same_thread": False, "timeout": 30}
        self._engine = create_engine(database_url, connect_args=connect_args, future=True)
        if database_url.startswith("sqlite"):
            self._enable_sqlite_foreign_keys()
            self._serialize_sqlite_write_transactions()
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def _enable_sqlite_foreign_keys(self) -> None:
        """SQLite ignores `FOREIGN KEY` constraints unless told otherwise per
        connection — without this, a bad `session_id` on a child row would insert
        silently instead of raising, and Postgres (the production target, which
        enforces FKs by default) would behave differently from every test.
        """

        @event.listens_for(self._engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    def _serialize_sqlite_write_transactions(self) -> None:
        """Makes every transaction acquire SQLite's write lock at `BEGIN`, not at
        the first write — the documented pysqlite recipe for this
        (https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl).

        Without this, `EventRepository.append()`'s `SELECT MAX(sequence)` and its
        `INSERT` are two separate lock acquisitions: many connections can read the
        same MAX before any of them writes, so under real concurrency more than
        `EVENT_SEQUENCE_MAX_ATTEMPTS` writers can collide on the same computed
        sequence. `BEGIN IMMEDIATE` closes that window by taking the write lock
        immediately, turning concurrent writers into a queue (blocking, via the
        `timeout` connect arg, rather than racing) — the retry-on-`IntegrityError`
        backstop then only has to handle a true anomaly, not a thundering herd.
        """

        @event.listens_for(self._engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection: object, _: object) -> None:
            dbapi_connection.isolation_level = None  # type: ignore[attr-defined]

        @event.listens_for(self._engine, "begin")
        def _begin_immediate(conn: object) -> None:
            conn.exec_driver_sql("BEGIN IMMEDIATE")  # type: ignore[attr-defined]

    def create_all(self) -> None:
        """Creates every table registered on `Base.metadata`. Idempotent."""
        Base.metadata.create_all(self._engine)
        logger.info("database initialized: %s", self._database_url)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Commits on success, rolls back on exception, always closes."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
