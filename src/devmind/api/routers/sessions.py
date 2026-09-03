"""Session + approval-gate HTTP surface (E11-F2).

Thin by rule: each handler translates the request, calls one `SessionService`
method, and returns a schema. No business logic, no ORM model, and no
`HTTPException` — every domain failure is a `DevMindError` the error handler maps to
RFC-7807 (Claude.md §1).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from devmind.api.dependencies import (
    EventStreamServiceDep,
    SessionRunnerDep,
    SessionServiceDep,
)
from devmind.core.constants import API_DEFAULT_PAGE_LIMIT, API_MAX_PAGE_LIMIT, API_V1_PREFIX
from devmind.core.enums import SessionStatus
from devmind.schemas.approval import ApprovalDecisionRequest, ApprovalRead, ApprovalRequest
from devmind.schemas.event import EventRead
from devmind.schemas.session import SessionCreate, SessionRead, SessionSummary

router = APIRouter(prefix=f"{API_V1_PREFIX}/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_202_ACCEPTED)
async def create_session(
    body: SessionCreate,
    background: BackgroundTasks,
    service: SessionServiceDep,
    runner: SessionRunnerDep,
) -> SessionRead:
    """Create the session and schedule its run; return `202` immediately."""
    session = service.create(body)
    background.add_task(runner.launch, session.id)
    return session


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    service: SessionServiceDep,
    status_filter: Annotated[SessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=API_MAX_PAGE_LIMIT)] = API_DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionSummary]:
    return service.list_summaries(status=status_filter, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(session_id: str, service: SessionServiceDep) -> SessionRead:
    return service.get(session_id)


@router.get("/{session_id}/events", response_model=list[EventRead])
async def get_events(
    session_id: str,
    service: SessionServiceDep,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=API_MAX_PAGE_LIMIT)] = API_MAX_PAGE_LIMIT,
) -> list[EventRead]:
    return service.events(session_id, after_sequence=after_sequence, limit=limit)


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: str,
    streams: EventStreamServiceDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after_sequence: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    """SSE live feed. `Last-Event-ID` (or `?after_sequence=`) resumes after the gap.

    Deliberately does not depend on the db-bound `SessionService`: that dependency's
    unit-of-work scope would stay open for the whole stream and block the poller's
    own writes on SQLite. The existence check runs in its own short scope instead.
    """
    streams.assert_session_exists(session_id)  # 404 before the stream opens
    after = (
        _parse_last_event_id(last_event_id) if last_event_id is not None else (after_sequence or 0)
    )
    return StreamingResponse(
        streams.stream(session_id, after_sequence=after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/approval-request", response_model=ApprovalRequest)
async def get_approval_request(session_id: str, service: SessionServiceDep) -> ApprovalRequest:
    return await service.approval_request(session_id)


@router.post("/{session_id}/approval", response_model=ApprovalRead)
async def decide_approval(
    session_id: str, body: ApprovalDecisionRequest, service: SessionServiceDep
) -> ApprovalRead:
    return await service.decide(session_id, body)


@router.get("/{session_id}/diff", response_class=PlainTextResponse)
async def get_diff(session_id: str, service: SessionServiceDep) -> str:
    return await service.diff(session_id)


@router.post(
    "/{session_id}/cancel", response_model=SessionRead, status_code=status.HTTP_202_ACCEPTED
)
async def cancel_session(session_id: str, service: SessionServiceDep) -> SessionRead:
    return service.cancel(session_id)


def _parse_last_event_id(raw: str | None) -> int:
    """A `Last-Event-ID` of a bad shape resumes from the start rather than 400-ing —
    losing a replay is better than dropping the reconnect.
    """
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
