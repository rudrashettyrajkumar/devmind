# Spec — E1: Foundation & Project Skeleton

| | |
|---|---|
| **Epic** | E1 |
| **Depends on** | — |
| **Blocks** | everything |
| **Size** | M (~1.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

Stand up a runnable, typed, linted, tested skeleton so that no later epic ever has to make a
structural decision. Every directory, every config knob, every enum value that the rest of the
build depends on exists after this epic — empty of behaviour but correct in shape.

## Out of scope

No domain logic, no database tables, no agent. Just the frame.

## Deliverables

```
pyproject.toml · Makefile · .env.example · .gitignore · README.md (stub)
src/devmind/
  __init__.py  main.py
  api/         __init__.py  health.py  errors.py
  services/    __init__.py
  repositories/__init__.py
  models/      __init__.py
  schemas/     __init__.py
  interfaces/  __init__.py
  tools/       __init__.py
  core/        __init__.py  config.py  constants.py  enums.py  logging.py
  prompts/     __init__.py
  exceptions/  __init__.py  base.py
tests/         conftest.py + mirror packages
```

## Contracts

### `core/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore")

    # Providers
    anthropic_api_key: str = Field(...)
    github_token: str | None = Field(default=None)

    # Persistence
    database_url: str = Field(default="sqlite:///./devmind.db")

    # Agent
    agent_model: str = Field(default="claude-opus-5")
    agent_effort: str = Field(default="high")
    max_fix_attempts: int = Field(default=3, ge=1, le=5)
    max_agent_steps_per_phase: int = Field(default=40, ge=1)
    max_session_cost_usd: float = Field(default=5.0, gt=0)

    # Sandbox
    sandbox_backend: SandboxBackend = Field(default=SandboxBackend.AUTO)
    sandbox_command_timeout_seconds: int = Field(default=300, gt=0)
    sandbox_image: str = Field(default="python:3.12-slim")

    # Workspace
    workspace_root: Path = Field(default=Path("./workspaces"))
    max_concurrent_sessions: int = Field(default=2, ge=1)

    # Ops
    log_level: str = Field(default="INFO")
    dry_run: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Every field typed, defaulted where safe, and constrained where a bad value is silently harmful.
`anthropic_api_key` has no default — the app must fail fast rather than run half-configured.

### `core/enums.py`

```python
class SessionStatus(StrEnum):
    CREATED = "created";            INGESTING = "ingesting"
    PLANNING = "planning";          INVESTIGATING = "investigating"
    EDITING = "editing";            TESTING = "testing"
    SUMMARIZING = "summarizing";    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved";          PR_OPENED = "pr_opened"
    REJECTED = "rejected";          EXHAUSTED = "exhausted"
    FAILED = "failed";              HALTED = "halted"

    def is_terminal(self) -> bool: ...
    def can_transition_to(self, target: "SessionStatus") -> bool: ...
```

Also: `EventType`, `TodoStatus`, `ApprovalDecision`, `SandboxBackend` (`AUTO`/`DOCKER`/
`SUBPROCESS`), `AgentPhase` (`PLANNING`/`INVESTIGATION`/`EDITING`/`TESTING`/`SUMMARIZING`),
`ToolName`, `StopReason`.

The transition map itself is E2's work (E2-F3-T3); E1 defines the values and the method
signatures so nothing has to be renamed later.

### `core/constants.py`

All `Final`. At minimum:

```python
MAX_FIX_ATTEMPTS: Final[int] = 3
MAX_AGENT_STEPS_PER_PHASE: Final[int] = 40
MAX_TOOL_RESULT_CHARS: Final[int] = 20_000
MAX_TEST_OUTPUT_CHARS: Final[int] = 30_000
MAX_FILE_READ_LINES: Final[int] = 2_000
MAX_DIFF_CHARS: Final[int] = 100_000
SANDBOX_COMMAND_TIMEOUT_SECONDS: Final[int] = 300
DEPENDENCY_INSTALL_TIMEOUT_SECONDS: Final[int] = 900
ALLOWED_COMMAND_BINARIES: Final[frozenset[str]] = frozenset({
    "python", "python3", "pytest", "uv", "pip", "ruff", "mypy", "git", "ls", "cat",
})
BRANCH_PREFIX: Final[str] = "devmind"
MODEL_PRICING: Final[Mapping[str, ModelPrice]] = {
    "claude-opus-5":   ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0),
    "claude-sonnet-5": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0),
    "claude-haiku-4-5":ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
}
CACHE_READ_DISCOUNT: Final[float] = 0.1
```

> Note the split: `MAX_FIX_ATTEMPTS` appears in both `constants.py` and `Settings`. The
> constant is the default the business logic reads; the setting is the operator override.
> `Settings.max_fix_attempts` defaults **to the constant** — write it that way, don't duplicate
> the literal.

### `exceptions/`

```python
class DevMindError(Exception):
    """Base for everything this application raises."""
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None: ...
```

Subclasses: `ConfigurationError`, `WorkspaceError`, `PathEscapeError`, `SandboxError`,
`SandboxTimeoutError`, `LLMProviderError`, `ToolExecutionError`, `InvalidStateTransitionError`,
`ApprovalRequiredError`, `ApprovalAlreadyConsumedError`, `BudgetExceededError`, `GitHubError`,
`RepositoryIngestionError`.

Each carries an HTTP status hint used by the single API error handler — the mapping lives with
the exception, not scattered through routers.

### `core/logging.py`

`LoggingConfigurator` class (not loose functions — `Claude.md` §5): JSON formatter, a
`contextvars`-backed `session_id` filter so every line of a run is greppable by session, and a
`configure(level: str)` entry point called from the app lifespan.

### `main.py`

```python
class ApplicationFactory:
    def create(self) -> FastAPI: ...
```

Lifespan does three things and logs each: initialise the database, probe the sandbox backend
and log which one won, verify the LLM provider is reachable. Register routers and the single
error handler. `app = ApplicationFactory().create()` at module scope for uvicorn.

### `api/health.py`

`GET /health` → `HealthRead { status, version, database, sandbox_backend, provider_reachable }`.
This is what tells an operator, before a ten-minute run, that `gh` isn't authenticated or Docker
isn't there.

## Task plan

| Task | Detail |
|---|---|
| E1-F1-T1 | `pyproject.toml` — src layout, `[project]`, `[tool.ruff]` (line-length 100, select `E,F,I,N,UP,B,SIM,RUF`), `[tool.mypy]` strict, `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| E1-F1-T2 | Create the full package tree with `__init__.py` everywhere |
| E1-F1-T3 | Get `ruff` and `mypy --strict` clean on the skeleton |
| E1-F1-T4 | `Makefile`: `install`, `lint`, `format`, `typecheck`, `test`, `check`, `run` |
| E1-F2-T1 | `Settings` + `get_settings()` |
| E1-F2-T2 | `.env.example` — every variable, secrets blank, comments |
| E1-F2-T3 | `constants.py` |
| E1-F2-T4 | `enums.py` |
| E1-F3-T1 | Exception hierarchy |
| E1-F3-T2 | `LoggingConfigurator` |
| E1-F4-T1 | `ApplicationFactory` + lifespan |
| E1-F4-T2 | `/health` |
| E1-F4-T3 | RFC-7807 error handler |
| E1-F4-T4 | `tests/` tree + `conftest.py` skeleton |

## Testing

- `test_config.py` — settings load from env; a missing `anthropic_api_key` raises; constrained
  fields reject out-of-range values.
- `test_enums.py` — every enum member's value is the expected string; `is_terminal()` behaves.
- `test_exceptions.py` — hierarchy is correct; `details` round-trips.
- `test_health.py` — `TestClient` gets 200 and a well-formed body.
- `test_logging.py` — the session-id filter injects into a record.

## Acceptance criteria

- [ ] `make check` is green: ruff, ruff format, mypy --strict, pytest.
- [ ] `make run` boots uvicorn and `/health` returns 200 naming the resolved sandbox backend.
- [ ] `.env.example` documents every setting; no secret has a real default.
- [ ] No literal used twice anywhere outside `constants.py`.
- [ ] The package tree matches `Claude.md` §1 exactly.

## Notes for the implementer

- Do **not** create abstract base classes in this epic. Nothing has two implementations yet.
- Do **not** create a `utils.py`. If you feel the urge, name the class instead.
- The primary dev machine has **no Docker**. `SandboxBackend.AUTO` must resolve cleanly to
  `SUBPROCESS` and log a warning — that path is the default developer experience, not an
  afterthought.
