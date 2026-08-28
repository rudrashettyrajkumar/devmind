# Spec — E11: API, Streaming & Operator UX

| | |
|---|---|
| **Epic** | E11 |
| **Depends on** | E2, E9 |
| **Blocks** | E12 |
| **Size** | M (~1.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

Make a ten-minute autonomous run observable and controllable by a human. Without this, the
system is a black box that occasionally emits a PR — and a black box is exactly what the
approval gate exists to prevent.

## Design references

`docs/01-solution-design.md` §12 (API surface), §15 (observability).

## Contracts

### Routers — thin, always

`api/` translates HTTP to service calls and back. No business logic, no ORM models, no
`HTTPException` raised anywhere but the error handler.

```python
class SessionRouter:
    def __init__(self, sessions: SessionService, orchestrator: SessionOrchestrator) -> None: ...
```

| Method | Path | Returns |
|---|---|---|
| `POST` | `/api/v1/sessions` | `202` + `SessionRead`; schedules the run as a background task |
| `GET` | `/api/v1/sessions` | `list[SessionSummary]`, `?status=` filter, paginated |
| `GET` | `/api/v1/sessions/{id}` | `SessionRead` |
| `GET` | `/api/v1/sessions/{id}/events` | `list[EventRead]`, `?after_sequence=`, `?limit=` |
| `GET` | `/api/v1/sessions/{id}/stream` | SSE |
| `GET` | `/api/v1/sessions/{id}/approval-request` | `ApprovalRequest` (409 unless `AWAITING_APPROVAL`) |
| `POST` | `/api/v1/sessions/{id}/approval` | `ApprovalDecisionRequest` → `ApprovalRead` |
| `GET` | `/api/v1/sessions/{id}/diff` | `text/plain` |
| `POST` | `/api/v1/sessions/{id}/cancel` | `202` |
| `GET` | `/health` | `HealthRead` |

`POST /sessions` returns immediately. Concurrency is bounded by
`max_concurrent_sessions` via an `asyncio.Semaphore`; over the limit the session is created in
`CREATED` and picked up when a slot frees, rather than rejected — a queue of one process, not a
queue system.

```python
class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    decided_by: str = Field(min_length=1)      # required — see E9
    reason: str | None = None

    @model_validator(mode="after")
    def _reason_required_for_rejection(self) -> "ApprovalDecisionRequest": ...
```

### Dependency wiring

```python
class Container:
    """Composes the object graph. One place, so the wiring is readable."""
    def session_service(self) -> SessionService: ...
    def approval_service(self) -> ApprovalService: ...
    def orchestrator(self) -> SessionOrchestrator: ...
```

Exposed to FastAPI via `Depends`. A plain class, not a DI framework — the graph is a few dozen
nodes and a framework would be infrastructure with no requirement behind it (`Claude.md` §9).
This is also the seam that makes `app.dependency_overrides` trivial in API tests.

### SSE streaming

```python
class EventStreamService:
    def __init__(self, events: EventRepository, poll_interval: float = 0.5) -> None: ...

    async def stream(self, session_id: str,
                     after_sequence: int = 0) -> AsyncIterator[ServerSentEvent]: ...
```

- Each event: `id: <sequence>`, `event: <event_type>`, `data: <json payload>`.
- **Resumable.** The client's `Last-Event-ID` header sets `after_sequence`, so a reconnect
  replays from the log rather than losing the gap. This is the whole reason `sequence` is
  monotonic and unique.
- Heartbeat comment every 15s so proxies don't kill an idle connection during a long test run.
- Terminates on a terminal status, after flushing the final event.
- Clean disconnect: `asyncio.CancelledError` handled, no leaked task, no leaked DB session.

Polling the event table at 0.5s is the right implementation here. An in-process pub/sub would be
faster and would also be the premature infrastructure `Claude.md` §9 warns about — one process,
a local database, a half-second latency budget.

### Error mapping

One handler, in `api/errors.py`, mapping `DevMindError` subclasses to RFC-7807:

| Exception | Status |
|---|---|
| `InvalidStateTransitionError` | 409 |
| `ApprovalRequiredError` | 403 |
| `ApprovalAlreadyConsumedError` | 409 |
| `RepositoryIngestionError` | 422 |
| `PathEscapeError`, `SandboxError` | 400 |
| `BudgetExceededError` | 402 |
| `GitHubError` | 502 |
| unmapped `DevMindError` | 500 |

```json
{"type": "/errors/approval-required", "title": "Approval required",
 "status": 403, "detail": "Session 3f9a… has not been approved", "instance": "/api/v1/..."}
```

### CLI client

```python
class DevMindCLI:
    def run(self, repo: str, issue: int) -> None: ...
    def watch(self, session_id: str) -> None: ...
    def review(self, session_id: str) -> None: ...
    def approve(self, session_id: str, by: str) -> None: ...
    def reject(self, session_id: str, by: str, reason: str) -> None: ...
    def status(self, session_id: str) -> None: ...
```

`rich`-rendered live view: current status, the todo plan with per-item state, the last few tool
calls, attempts used, elapsed time, and running cost.

`review` renders the full `ApprovalRequest` — summary, warnings **first**, diff with syntax
highlighting, test evidence, risk notes.

`approve` requires typing the session id to confirm. Not a y/n keypress: approving an
autonomous agent's code change should take a deliberate second, and a single keystroke next to
"n" is not deliberate.

## Task plan

E11-F1-T1 … E11-F3-T3. Container → routers → error mapping → SSE → CLI.

## Testing

| Test | Proves |
|---|---|
| `test_sessions_api.py` | Create returns 202 + id; get; list with filter; 404 on unknown id |
| `test_approvals_api.py` | 409 unless `AWAITING_APPROVAL`; approve/reject; `decided_by` required; rejection requires a reason |
| `test_events_api.py` | Pagination by `after_sequence`; diff endpoint returns `text/plain` |
| `test_error_mapping.py` | Each `DevMindError` maps to its status and an RFC-7807 body |
| `test_sse_stream.py` | Events emitted in order; `Last-Event-ID` resumes at the right sequence; heartbeat present; stream closes on terminal status |
| `test_sse_disconnect.py` | Client disconnect leaves no pending task |
| `test_cli.py` | Command parsing; `approve` refuses without the typed confirmation |

Use `TestClient` with `app.dependency_overrides` pointed at fakes. No API test starts a real
session run.

## Acceptance criteria

- [ ] An operator can start, watch live, review, and approve or reject entirely from the CLI.
- [ ] SSE resumes correctly after a mid-run reconnect; no events lost.
- [ ] Every `DevMindError` maps to a correct RFC-7807 response.
- [ ] No router imports an ORM model; no service raises `HTTPException`.
- [ ] `approve` requires an explicit typed confirmation.
- [ ] `make check` green.

## Notes

- Keep routers boring. If a router grows a conditional over domain state, that logic belongs in
  a service.
- Never expose the approval token over the API — approval is authorised by the caller's
  identity and the session state, not by a bearer secret in a URL.
- No web UI (design §2). The CLI plus SSE is the operator surface.
