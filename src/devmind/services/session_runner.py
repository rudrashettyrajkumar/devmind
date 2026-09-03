"""`SessionRunner` — schedules and bounds the long autonomous run (E11-F1).

`POST /sessions` returns `202` immediately and hands the session id here as a
background task. `launch()` waits on an `asyncio.Semaphore` sized to
`max_concurrent_sessions`: over the limit the session simply stays `CREATED` until a
slot frees — a queue of one process, not a queue system (spec §Routers).

The run is one unit of work: `launch()` opens a single `session_scope()`, builds the
orchestrator against it, and runs it to a terminal status. Any unhandled error is
logged and the session is left `FAILED` by the orchestrator's own `finally`; the
runner never crashes the server.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.database import DatabaseManager
from devmind.services.session_orchestrator import SessionOrchestrator

logger = logging.getLogger(__name__)

OrchestratorFactory = Callable[[SQLAlchemySession], SessionOrchestrator]


class SessionRunner:
    """Bounds concurrency and owns the background lifetime of a run."""

    def __init__(
        self,
        database: DatabaseManager,
        orchestrator_factory: OrchestratorFactory,
        *,
        max_concurrent: int,
    ) -> None:
        self._database = database
        self._make_orchestrator = orchestrator_factory
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def launch(self, session_id: str) -> None:
        """Acquire a slot, then run `session_id` to completion. Safe to `add_task`."""
        async with self._semaphore:
            logger.info("session %s: run starting", session_id)
            try:
                with self._database.session_scope() as db:
                    await self._make_orchestrator(db).run(session_id)
            except Exception:
                logger.exception("session %s: run crashed", session_id)
            else:
                logger.info("session %s: run finished", session_id)
