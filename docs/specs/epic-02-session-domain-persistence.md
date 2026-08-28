# Spec — E2: Session Domain & Persistence

| | |
|---|---|
| **Epic** | E2 |
| **Depends on** | E1 |
| **Blocks** | E3, E4, E7, E9, E11 |
| **Size** | L (~2 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

The session aggregate, its state machine, and an append-only event log. After this epic, a
session is a durable, inspectable, replayable object — which is what makes a ten-minute
autonomous run auditable instead of magic.

## Design references

`docs/01-solution-design.md` §5 (lifecycle), §11 (data model), §15 (event types).

## Contracts

### Models — SQLAlchemy 2.0 only

```python
class Base(DeclarativeBase):
    pass

class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=lambda: str(uuid4()))

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

class SessionModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"
    repo_url: Mapped[str]
    issue_number: Mapped[int | None]
    issue_title: Mapped[str | None]
    issue_body: Mapped[str | None]
    base_commit_sha: Mapped[str | None]
    default_branch: Mapped[str | None]
    workspace_path: Mapped[str | None]
    branch_name: Mapped[str | None]
    status: Mapped[SessionStatus] = mapped_column(default=SessionStatus.CREATED, index=True)
    sandbox_backend: Mapped[SandboxBackend | None]
    fix_attempts: Mapped[int] = mapped_column(default=0)
    total_steps: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    has_test_suite: Mapped[bool] = mapped_column(default=True)
    failure_reason: Mapped[str | None]
    completed_at: Mapped[datetime | None]
```

Plus `EventModel`, `TodoItemModel`, `TestRunModel`, `ApprovalModel`, `PullRequestModel` per
design §11. `EventModel` carries `UniqueConstraint("session_id", "sequence")`.

Store enums as their `StrEnum` value with a SQLAlchemy `Enum(..., native_enum=False)` — the
column reads as a legible string in the DB and validates on write.

### `core/database.py`

```python
class DatabaseManager:
    def __init__(self, database_url: str) -> None: ...
    def create_all(self) -> None: ...
    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Commits on success, rolls back on exception, always closes."""
```

This class and `repositories/` are the **only** places `sqlalchemy.orm.Session` may be
imported. The standards auditor greps for it.

### Repositories

```python
class SessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: SessionCreate) -> SessionModel: ...
    def get_by_id(self, session_id: str) -> SessionModel | None: ...
    def list(self, *, status: SessionStatus | None = None,
             limit: int = 50, offset: int = 0) -> list[SessionModel]: ...
    def update_status(self, session_id: str, status: SessionStatus,
                      *, failure_reason: str | None = None) -> SessionModel: ...
    def record_usage(self, session_id: str, usage: TokenUsage, cost_usd: float) -> None: ...
    def increment_fix_attempts(self, session_id: str) -> int: ...
```

```python
class EventRepository:
    def append(self, session_id: str, event_type: EventType,
               payload: Mapping[str, object]) -> EventModel:
        """Allocates the next sequence atomically. Never overwrites."""
    def list_since(self, session_id: str, after_sequence: int = 0,
                   limit: int = 200) -> list[EventModel]: ...
```

Sequence allocation must be race-safe. Use `SELECT COALESCE(MAX(sequence),0)+1 ... ` inside the
same transaction as the insert, and rely on the unique constraint as the backstop: on
`IntegrityError`, retry once. The test proves it under concurrent appends.

Repositories return **ORM models**; services convert to schemas. Repositories contain no
business rules — `update_status` writes what it's told; deciding whether the transition is legal
is the state machine's job.

### The state machine

```python
_LEGAL_TRANSITIONS: Final[Mapping[SessionStatus, frozenset[SessionStatus]]] = {
    SessionStatus.CREATED:        frozenset({INGESTING, FAILED, HALTED}),
    SessionStatus.INGESTING:      frozenset({PLANNING, FAILED, HALTED}),
    SessionStatus.PLANNING:       frozenset({INVESTIGATING, FAILED, HALTED}),
    SessionStatus.INVESTIGATING:  frozenset({EDITING, FAILED, HALTED}),
    SessionStatus.EDITING:        frozenset({TESTING, FAILED, HALTED}),
    SessionStatus.TESTING:        frozenset({EDITING, SUMMARIZING, EXHAUSTED, FAILED, HALTED}),
    SessionStatus.SUMMARIZING:    frozenset({AWAITING_APPROVAL, FAILED, HALTED}),
    SessionStatus.AWAITING_APPROVAL: frozenset({APPROVED, REJECTED, HALTED}),
    SessionStatus.APPROVED:       frozenset({PR_OPENED, FAILED}),
    # terminals map to frozenset()
}
```

```python
class SessionStateMachine:
    def __init__(self, sessions: SessionRepository, events: EventRepository) -> None: ...

    def transition(self, session_id: str, target: SessionStatus,
                   *, reason: str | None = None) -> SessionModel:
        """Validates, persists, emits STATE_CHANGED. Raises InvalidStateTransitionError."""
```

Two properties this buys, and they are the reason it exists:
`PR_OPENED` is reachable only from `APPROVED`, and `APPROVED` only from `AWAITING_APPROVAL`
(safety layer 2, design §9). Any other route to a PR is structurally impossible.

### Schemas

`SessionCreate` (repo_url validated as a URL, `issue_number` xor `issue_description`),
`SessionRead` (`from_attributes=True`), `SessionSummary`, `EventRead`, `TodoItemRead`.

`SessionCreate` validation: exactly one of `issue_number` / `issue_description` must be present
— a model validator, not a runtime `if` in a service.

## Task plan

Follow E2-F1-T1 … E2-F3-T5 from `docs/02-epic-breakdown.md` in order. Models → database
manager → repositories → schemas → state machine → tests.

## Testing

| Test | Proves |
|---|---|
| `test_session_repository.py` | CRUD, status filter, usage accumulation, missing-id returns `None` |
| `test_event_repository.py` | Sequence starts at 1, is monotonic, is unique; `list_since` paginates |
| `test_event_repository_concurrency.py` | 50 concurrent appends → sequences 1..50, no gaps, no duplicates |
| `test_state_machine.py` | Every legal transition succeeds; **every** illegal pair raises; terminals accept nothing |
| `test_state_machine_events.py` | Each transition emits exactly one `STATE_CHANGED` with from/to |
| `test_schemas_session.py` | `SessionCreate` rejects both-or-neither issue inputs; bad URL rejected |

The illegal-transition test should be generated over the full cartesian product of statuses
minus the legal map — that way adding a status without updating the map fails the suite.

## Acceptance criteria

- [ ] A session can be created, driven through the full happy path, and read back.
- [ ] The event log replays the run in order with no gaps.
- [ ] Every illegal transition raises `InvalidStateTransitionError`; proven exhaustively.
- [ ] `PR_OPENED` is unreachable except from `APPROVED` — asserted by a named test.
- [ ] No `sqlalchemy` import outside `repositories/`, `models/`, `core/database.py`.
- [ ] `make check` green.

## Notes

- No Alembic in v1. `create_all()` on startup is right for a single-process app with no
  production data yet; introducing migrations before there's a schema to migrate is exactly the
  premature infrastructure `Claude.md` §9 warns about. Note it as a follow-up in the README.
- Don't add a generic `BaseRepository[T]`. Three repositories with different query shapes do
  not justify a generic — write them plainly.
