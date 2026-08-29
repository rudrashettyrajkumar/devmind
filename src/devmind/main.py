"""DevMind's FastAPI entry point. `app` is built once at module scope for uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from devmind.api.errors import ErrorHandlerRegistrar
from devmind.api.health import router as health_router
from devmind.core.config import Settings, get_settings
from devmind.core.logging import LoggingConfigurator
from devmind.services.sandbox_factory import SandboxFactory

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


class ApplicationFactory:
    """Builds the FastAPI application: lifespan, routers, and the one error handler.

    Each lifespan step is logged individually, so a startup failure names exactly
    which precondition was unmet — an operator should never have to guess whether it
    was the database, the sandbox, or a missing credential.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create(self) -> FastAPI:
        app = FastAPI(
            title="DevMind",
            version=__version__,
            lifespan=self._lifespan,
        )
        app.include_router(health_router)
        ErrorHandlerRegistrar().register(app)
        return app

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        LoggingConfigurator().configure(self._settings.log_level)

        # 1. Database — no models until E2; report the honest current state.
        app.state.database_status = "not_configured"
        logger.info("database: not_configured (models arrive in E2)")

        # 2. Sandbox backend — resolve AUTO to a concrete backend, once. An explicit
        #    DOCKER that is unreachable raises ConfigurationError here and aborts
        #    startup rather than downgrading isolation silently (E5-F2-T3).
        resolved_backend = SandboxFactory(self._settings).resolve_backend()
        app.state.sandbox_backend = resolved_backend
        logger.info("sandbox backend resolved: %s", resolved_backend.value)

        # 3. LLM provider — credential-presence check only until AnthropicProvider
        #    lands in E3; no network call is made here, and `anthropic` is not
        #    imported until E3 (see docs/specs/epic-03-llm-provider-prompt-system.md).
        app.state.provider_reachable = bool(self._settings.anthropic_api_key)
        logger.info("provider credential configured: %s", app.state.provider_reachable)

        app.state.version = __version__

        yield


app = ApplicationFactory().create()
