"""FastAPI dependency providers — the seam between `Container` and the routers.

Every router dependency resolves through a function here, so an API test overrides
one function with `app.dependency_overrides` and never has to touch the graph. The
`Annotated[...]` aliases at the bottom are what the routers import.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.api.container import Container
from devmind.services.event_stream_service import EventStreamService
from devmind.services.session_runner import SessionRunner
from devmind.services.session_service import SessionService


def get_container(request: Request) -> Container:
    """The process-wide container, stashed on `app.state` by `ApplicationFactory`."""
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):  # pragma: no cover - misconfiguration
        raise RuntimeError("application container is not configured on app.state")
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_db(container: ContainerDep) -> Iterator[SQLAlchemySession]:
    """One request-scoped unit of work: committed on success, rolled back on error."""
    with container.database.session_scope() as db:
        yield db


DbDep = Annotated[SQLAlchemySession, Depends(get_db)]


def get_session_service(db: DbDep, container: ContainerDep) -> SessionService:
    return container.session_service(db)


def get_event_stream_service(container: ContainerDep) -> EventStreamService:
    return container.event_stream_service


def get_session_runner(container: ContainerDep) -> SessionRunner:
    return container.session_runner


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
EventStreamServiceDep = Annotated[EventStreamService, Depends(get_event_stream_service)]
SessionRunnerDep = Annotated[SessionRunner, Depends(get_session_runner)]
