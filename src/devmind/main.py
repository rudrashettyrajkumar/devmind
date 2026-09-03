"""DevMind's FastAPI entry point. `app` is built once at module scope for uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from devmind.api.container import Container
from devmind.api.errors import ErrorHandlerRegistrar
from devmind.api.health import router as health_router
from devmind.api.routers.sessions import router as sessions_router
from devmind.core.config import Settings, get_settings
from devmind.core.database import DatabaseManager
from devmind.core.logging import LoggingConfigurator
from devmind.services.sandbox_factory import SandboxFactory

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


class ApplicationFactory:
    """Builds the FastAPI application: lifespan, routers, the error handler, and the
    one `Container` every router dependency resolves through.

    Each lifespan step is logged individually, so a startup failure names exactly
    which precondition was unmet — an operator should never have to guess whether it
    was the database, the sandbox, or a missing credential.
    """

    def __init__(
        self, settings: Settings | None = None, database: DatabaseManager | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._database = database

    def create(self) -> FastAPI:
        app = FastAPI(title="DevMind", version=__version__, lifespan=self._lifespan)
        app.include_router(health_router)
        app.include_router(sessions_router)
        ErrorHandlerRegistrar().register(app)
        return app

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        LoggingConfigurator().configure(self._settings.log_level)

        # 1. Database — create the schema (idempotent; no Alembic in v1, Claude.md §9).
        database = self._database or DatabaseManager(self._settings.database_url)
        database.create_all()
        app.state.database_status = "ok"
        logger.info("database ready: %s", self._settings.database_url)

        # 2. Sandbox backend — resolve AUTO to a concrete backend, once. An explicit
        #    DOCKER that is unreachable raises ConfigurationError here and aborts
        #    startup rather than downgrading isolation silently (E5-F2-T3).
        resolved_backend = SandboxFactory(self._settings).resolve_backend()
        app.state.sandbox_backend = resolved_backend
        logger.info("sandbox backend resolved: %s", resolved_backend.value)

        # 3. LLM provider — credential-presence check only; no network call at startup.
        app.state.provider_reachable = bool(self._settings.anthropic_api_key)
        logger.info("provider credential configured: %s", app.state.provider_reachable)

        # 4. The object graph — one place, on app.state, for every router dependency.
        app.state.container = Container(self._settings, database)
        app.state.version = __version__

        yield


app = ApplicationFactory().create()
