# DevMind — Epic / Feature / Task Breakdown

Companion to `docs/01-solution-design.md`. Twelve epics, each with features and concrete
tasks. IDs are stable and are referenced by the specs in `docs/specs/` and the build prompts in
`docs/03-build-prompts.md`.

**ID scheme:** `E<n>` epic · `E<n>-F<m>` feature · `E<n>-F<m>-T<k>` task.
**Size:** S ≈ ½ day · M ≈ 1 day · L ≈ 2 days.

---

## Dependency graph

```
E1 ──► E2 ──► E3 ──┐
 │                 │
 ├──► E4 ──► E5 ───┼──► E6 ──► E7 ──► E8 ──► E9 ──► E10 ──► E11 ──► E12
 │                 │
 └─────────────────┘
```

| Epic | Title | Depends on | Size |
|---|---|---|---|
| E1 | Foundation & Project Skeleton | — | M |
| E2 | Session Domain & Persistence | E1 | L |
| E3 | LLM Provider & Prompt System | E1, E2 | L |
| E4 | Workspace & Repository Ingestion | E1, E2 | M |
| E5 | Sandbox Execution Layer | E1, E4 | L |
| E6 | Tool Framework & Tool Suite | E3, E4, E5 | L |
| E7 | Agent Loop & Planning | E3, E6 | L |
| E8 | Test Execution & Self-Correction | E5, E7 | L |
| E9 | Human Approval Gate & Safety | E2, E7, E8 | L |
| E10 | GitHub Integration & PR Delivery | E9 | M |
| E11 | API, Streaming & Operator UX | E2, E9 | M |
| E12 | Quality, Hardening & Delivery | all | L |

---

## E1 — Foundation & Project Skeleton

**Goal:** a runnable, typed, linted, tested skeleton that every later epic drops into without
touching structure.
**Value:** removes all structural decisions from the critical path.

### E1-F1 — Package & tooling
| Task | Description | Size |
|---|---|---|
| E1-F1-T1 | `pyproject.toml`: src layout, `uv`, deps (fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy 2, anthropic, python-frontmatter, pyyaml, httpx2, docker, rich), dev deps (pytest, pytest-asyncio, pytest-cov, ruff, mypy) | S |
| E1-F1-T2 | Full `src/devmind/` tree per `Claude.md` §1 with `__init__.py` in every package | S |
| E1-F1-T3 | `ruff` (line 100, `E,F,I,N,UP,B,SIM,RUF`) + `mypy --strict` config; both clean on the skeleton | S |
| E1-F1-T4 | `Makefile` / `justfile`: `install`, `lint`, `typecheck`, `test`, `run`, `check` | S |

### E1-F2 — Configuration & constants
| Task | Description | Size |
|---|---|---|
| E1-F2-T1 | `core/config.py` — `Settings(BaseSettings)`, every field typed and documented, `get_settings()` cached accessor | M |
| E1-F2-T2 | `.env.example` with every variable and a safe default; secrets blank | S |
| E1-F2-T3 | `core/constants.py` — all `Final`: `MAX_FIX_ATTEMPTS`, `MAX_AGENT_STEPS_PER_PHASE`, `MAX_TOOL_RESULT_CHARS`, `MAX_TEST_OUTPUT_CHARS`, `SANDBOX_COMMAND_TIMEOUT_SECONDS`, `ALLOWED_COMMAND_BINARIES`, `MODEL_PRICING`, `BRANCH_PREFIX` | S |
| E1-F2-T4 | `core/enums.py` — `SessionStatus`, `EventType`, `TodoStatus`, `ApprovalDecision`, `SandboxBackend`, `AgentPhase`, `ToolName`, `StopReason` | M |

### E1-F3 — Exceptions & logging
| Task | Description | Size |
|---|---|---|
| E1-F3-T1 | `exceptions/` — `DevMindError` base + `ConfigurationError`, `WorkspaceError`, `SandboxError`, `SandboxTimeoutError`, `LLMProviderError`, `ToolExecutionError`, `PathEscapeError`, `InvalidStateTransitionError`, `ApprovalRequiredError`, `ApprovalAlreadyConsumedError`, `BudgetExceededError`, `GitHubError` | S |
| E1-F3-T2 | `core/logging.py` — `LoggingConfigurator` class, JSON formatter, `session_id` contextvar filter | M |

### E1-F4 — App bootstrap
| Task | Description | Size |
|---|---|---|
| E1-F4-T1 | `main.py` — FastAPI factory, lifespan (DB init, sandbox probe, provider check), CORS | M |
| E1-F4-T2 | `api/health.py` — `GET /health` returning version, DB, sandbox backend, provider reachability | S |
| E1-F4-T3 | `api/errors.py` — one handler mapping `DevMindError` → RFC-7807 JSON | S |
| E1-F4-T4 | `tests/` mirror tree + `conftest.py` skeleton; `pytest` green | S |

**Acceptance:** `make check` passes (ruff + mypy strict + pytest); `uvicorn` boots; `/health`
returns 200 with the resolved sandbox backend named.

---

## E2 — Session Domain & Persistence

**Goal:** the session aggregate, its state machine, and an append-only event log.
**Value:** everything downstream has somewhere durable to write.

### E2-F1 — ORM models
| Task | Description | Size |
|---|---|---|
| E2-F1-T1 | `models/base.py` — `DeclarativeBase`, UUID pk mixin, timestamp mixin | S |
| E2-F1-T2 | `models/session.py` — `SessionModel` with all §11 columns, `Mapped[...]` style | M |
| E2-F1-T3 | `models/event.py` — `EventModel`, unique `(session_id, sequence)`, JSON payload | S |
| E2-F1-T4 | `models/todo.py`, `models/test_run.py`, `models/approval.py`, `models/pull_request.py` | M |
| E2-F1-T5 | `core/database.py` — `DatabaseManager` class: engine, `session_scope()` context manager, `create_all()` | M |

### E2-F2 — Repositories
| Task | Description | Size |
|---|---|---|
| E2-F2-T1 | `SessionRepository` — `create`, `get_by_id`, `list`, `update_status`, `record_usage` | M |
| E2-F2-T2 | `EventRepository` — `append` (allocates `sequence` atomically), `list_since`, `count` | M |
| E2-F2-T3 | `TodoRepository`, `TestRunRepository` | M |
| E2-F2-T4 | `ApprovalRepository`, `PullRequestRepository` | S |
| E2-F2-T5 | In-memory SQLite repository tests, including concurrent `append` sequence integrity | M |

### E2-F3 — Schemas & state machine
| Task | Description | Size |
|---|---|---|
| E2-F3-T1 | `schemas/session.py` — `SessionCreate`, `SessionRead`, `SessionSummary` (`from_attributes=True`) | M |
| E2-F3-T2 | `schemas/event.py`, `schemas/todo.py` | S |
| E2-F3-T3 | `SessionStatus.can_transition_to()` + full legal-transition map + `is_terminal()` | M |
| E2-F3-T4 | `SessionStateMachine` service — `transition()` raising `InvalidStateTransitionError`, emitting `STATE_CHANGED` | M |
| E2-F3-T5 | Exhaustive transition tests, legal and illegal, incl. every terminal state being a dead end | M |

**Acceptance:** a session can be created, transitioned through the full happy path, and
replayed from its event log; every illegal transition raises.

---

## E3 — LLM Provider & Prompt System

**Goal:** one typed seam to Claude, and prompts that live in markdown.
**Value:** deterministic tests everywhere downstream via `FakeLLMProvider`.

### E3-F1 — Provider abstraction
| Task | Description | Size |
|---|---|---|
| E3-F1-T1 | `interfaces/llm_provider.py` — `LLMProvider` ABC: `async complete(request: LLMRequest) -> LLMResponse` | S |
| E3-F1-T2 | `schemas/llm.py` — `LLMRequest`, `LLMResponse`, `ToolCall`, `ToolResultBlock`, `TokenUsage`, `StopReason` enum | M |
| E3-F1-T3 | `services/anthropic_provider.py` — `AnthropicProvider`: model from settings, adaptive thinking, `output_config.effort`, streaming for long calls, tool schemas passed through | L |
| E3-F1-T4 | Typed error chain: `NotFoundError` → `RateLimitError` → `APIStatusError` → `APIConnectionError` → `LLMProviderError`, with backoff on retryables only | M |
| E3-F1-T5 | `tests/fakes/fake_llm_provider.py` — scripted responses, call recording, assertion helpers | M |

### E3-F2 — Caching & cost
| Task | Description | Size |
|---|---|---|
| E3-F2-T1 | `cache_control` breakpoint placement: tools → system → stable brief; volatile content after the last breakpoint | M |
| E3-F2-T2 | `CostCalculator` — `MODEL_PRICING`, cache-read discount, per-session accumulation | M |
| E3-F2-T3 | Log `cache_read_input_tokens` per call; warn on sustained zero | S |
| E3-F2-T4 | Enable `context_management.edits = [clear_tool_uses_20250919]` behind a setting | M |

### E3-F3 — Prompt system
| Task | Description | Size |
|---|---|---|
| E3-F3-T1 | `prompts/loader.py` — `PromptLoader`: frontmatter parse, cache, `variables` validation, render | M |
| E3-F3-T2 | `schemas/prompt.py` — `PromptMetadata` (name, version, model, effort, description, variables) | S |
| E3-F3-T3 | Author all 7 prompt files (§13 of the design) | L |
| E3-F3-T4 | Test: every `prompts/*.md` loads, metadata validates, and declared variables render | M |

**Acceptance:** `FakeLLMProvider` drives a scripted multi-tool exchange end to end; no prompt
text exists in any `.py` file (enforced by a test that greps for it).

---

## E4 — Workspace & Repository Ingestion

**Goal:** turn `{repo_url, issue}` into an isolated workspace plus a navigable index.

### E4-F1 — Workspace management
| Task | Description | Size |
|---|---|---|
| E4-F1-T1 | `WorkspaceManager` — create `<root>/<session_id>/`, resolve, clean up, disk-usage guard | M |
| E4-F1-T2 | `WorkspacePathGuard` — resolve + `is_relative_to` + symlink rejection → `PathEscapeError` | M |
| E4-F1-T3 | Path-guard tests: `../`, absolute paths, symlink-out, `/etc/passwd`, nested traversal | M |

### E4-F2 — Repo ingestion
| Task | Description | Size |
|---|---|---|
| E4-F2-T1 | `RepoIngestionService.clone()` — shallow clone, record base SHA and default branch | M |
| E4-F2-T2 | `GitHubClient.fetch_issue()` — `gh issue view --json`; degrade to free-text description when no issue number given | M |
| E4-F2-T3 | Repo profiling: detect test framework, test dirs, dependency manager, entrypoints → `RepoProfile` | M |
| E4-F2-T4 | Ingestion failure handling: bad URL, private repo, missing issue, no default branch | S |

### E4-F3 — Code index
| Task | Description | Size |
|---|---|---|
| E4-F3-T1 | `CodeIndexService.build_tree()` — gitignore-aware file tree, depth- and count-capped | M |
| E4-F3-T2 | `SymbolIndexer` — Python `ast` walk → module/class/function map; regex fallback otherwise | L |
| E4-F3-T3 | `CodeSearchService` — ripgrep with `grep -rn` fallback, capped structured results | M |
| E4-F3-T4 | `RepoBrief` — compact, cacheable repo-structure summary injected into the system prefix | M |

**Acceptance:** ingesting a real public repo produces a workspace, a `RepoProfile`, a symbol
index, and a `RepoBrief` under a fixed token budget.

---

## E5 — Sandbox Execution Layer

**Goal:** run arbitrary repo commands without letting them out.

### E5-F1 — Contract
| Task | Description | Size |
|---|---|---|
| E5-F1-T1 | `interfaces/sandbox.py` — `Sandbox` ABC (`setup`/`run`/`teardown`) | S |
| E5-F1-T2 | `schemas/sandbox.py` — `SandboxCommand`, `CommandResult` (`exit_code`, `stdout`, `stderr`, `duration_seconds`, `timed_out`, `truncated`) | S |
| E5-F1-T3 | `OutputTruncator` — head+tail retention with an explicit truncation marker | S |

### E5-F2 — Implementations
| Task | Description | Size |
|---|---|---|
| E5-F2-T1 | `SubprocessSandbox` — cwd-pinned, scrubbed env, `setsid` group, timeout → group kill | L |
| E5-F2-T2 | `DockerSandbox` — image build/pull, `--network=none`, cpu/mem caps, non-root, workspace mount | L |
| E5-F2-T3 | `SandboxFactory` — settings-driven with a Docker liveness probe and logged fallback | M |
| E5-F2-T4 | Command allowlist enforcement + argv-only execution (never `shell=True`) | M |
| E5-F2-T5 | Dependency install step (`uv sync` / `pip install -e .`) with its own longer timeout | M |

### E5-F3 — Verification
| Task | Description | Size |
|---|---|---|
| E5-F3-T1 | Both backends pass one shared contract test suite (parametrised; Docker tests skip when absent) | L |
| E5-F3-T2 | Timeout test: a sleeping command is killed and reports `timed_out=True` | M |
| E5-F3-T3 | Network test: an outbound request fails inside the sandbox (Docker); subprocess backend logs its documented limitation | M |

**Acceptance:** both backends satisfy the same contract; timeouts kill process groups; the
active backend is recorded on the session.

---

## E6 — Tool Framework & Tool Suite

**Goal:** the agent's hands — typed, validated, audited, and incapable of reaching a remote.

### E6-F1 — Framework
| Task | Description | Size |
|---|---|---|
| E6-F1-T1 | `interfaces/tool.py` — `Tool` ABC: `name`, `description`, `input_model`, `async execute(input, ctx) -> ToolResult` | M |
| E6-F1-T2 | `ToolRegistry` — register, lookup, duplicate-name rejection, `to_api_schemas()` via `model_json_schema()` with `strict: true` | M |
| E6-F1-T3 | `ToolExecutor` — validate input, dispatch, catch everything into `is_error` results, emit `TOOL_CALL`/`TOOL_RESULT` events, truncate | L |
| E6-F1-T4 | `ToolContext` — workspace, path guard, sandbox, repo profile, session id | S |

### E6-F2 — Read tools
| Task | Description | Size |
|---|---|---|
| E6-F2-T1 | `ListDirTool` | S |
| E6-F2-T2 | `ReadFileTool` — line ranges, binary detection, truncation marker | M |
| E6-F2-T3 | `SearchCodeTool` | M |
| E6-F2-T4 | `FindSymbolTool` | M |

### E6-F3 — Write & exec tools
| Task | Description | Size |
|---|---|---|
| E6-F3-T1 | `WriteFileTool` — path-guarded, parent creation, size cap | M |
| E6-F3-T2 | `ApplyPatchTool` — exact-match replace; error on zero or multiple matches | L |
| E6-F3-T3 | `RunCommandTool` — allowlist + sandbox | M |
| E6-F3-T4 | `GitDiffTool` — capped working-tree diff | S |
| E6-F3-T5 | `TodoWriteTool` — persist plan, emit `PLAN_UPDATED` | M |
| E6-F3-T6 | `FinishTool` — structured phase exit with summary + confidence | S |

### E6-F4 — Safety verification
| Task | Description | Size |
|---|---|---|
| E6-F4-T1 | Per-tool unit tests including the failure paths | L |
| E6-F4-T2 | **Registry safety test:** no registered tool name or implementation references push/remote/network (SI-1) | M |
| E6-F4-T3 | Path-escape test applied to every path-taking tool | M |

**Acceptance:** every tool is registered, schema-valid, path-guarded, and error-safe; the
registry-safety test proves the agent has no route to a remote.

---

## E7 — Agent Loop & Planning

**Goal:** the long-horizon engine.

### E7-F1 — Loop core
| Task | Description | Size |
|---|---|---|
| E7-F1-T1 | `AgentContext` — message history, token estimate, step counter, phase, `to_request()` | L |
| E7-F1-T2 | `AgentLoop.run()` — call → tool → append, all results in one user message, per-step events | L |
| E7-F1-T3 | Step budget + `LoopOutcome` (`completed`, `budget_exhausted`, `failed`, `cancelled`) | M |
| E7-F1-T4 | `ContextCompactor` — truncation, stale-result clearing, plan/diff re-anchor | L |
| E7-F1-T5 | Cooperative cancellation checked every step | M |

### E7-F2 — Planning
| Task | Description | Size |
|---|---|---|
| E7-F2-T1 | `PlannerService` — issue + repo brief → todo plan via `planner` prompt | M |
| E7-F2-T2 | Plan persistence, versioning, and re-injection at each phase boundary | M |
| E7-F2-T3 | Plan-quality guards: non-empty, bounded item count, actionable phrasing | S |

### E7-F3 — Phase orchestration
| Task | Description | Size |
|---|---|---|
| E7-F3-T1 | `AgentPhase` enum + per-phase prompt/tool-subset selection | M |
| E7-F3-T2 | `SessionOrchestrator.run()` — the full state-machine drive, checkpointing each transition | L |
| E7-F3-T3 | Investigation phase: read-only tool subset, must end with a findings summary | M |
| E7-F3-T4 | Editing phase: write tools enabled, must produce a non-empty diff | M |
| E7-F3-T5 | Per-session cost ceiling enforcement → `BudgetExceededError` → `FAILED` | M |

**Acceptance:** with `FakeLLMProvider`, a scripted session runs `CREATED → … → TESTING`
deterministically; step budget, cost ceiling, and cancellation all halt it cleanly.

---

## E8 — Test Execution & Self-Correction

**Goal:** the feedback loop that makes autonomy real.

### E8-F1 — Test execution
| Task | Description | Size |
|---|---|---|
| E8-F1-T1 | `TestExecutionService` — build the pytest argv from `RepoProfile`, run in sandbox, persist a `TestRun` | M |
| E8-F1-T2 | Baseline run before any edit; classify pre-existing failures | M |
| E8-F1-T3 | Targeted re-runs (`node_ids` / `-k`) for fast iteration, with a full run before the gate | M |
| E8-F1-T4 | "No test suite" detection → proceed, flag the session `UNVERIFIED` | S |

### E8-F2 — Failure parsing
| Task | Description | Size |
|---|---|---|
| E8-F2-T1 | `PytestOutputParser` — summary counts, `FAILED` node ids, assertion messages, trimmed tracebacks | L |
| E8-F2-T2 | `TestFailureReport` schema + stable `signature` hash | M |
| E8-F2-T3 | Collection-error and import-error handling (distinct from assertion failures) | M |
| E8-F2-T4 | Parser tests against recorded real pytest output fixtures (pass, fail, error, collect-error, timeout) | L |

### E8-F3 — Correction controller
| Task | Description | Size |
|---|---|---|
| E8-F3-T1 | `SelfCorrectionController.decide()` → `RETRY` / `EXHAUSTED` / `SUCCEEDED`, honouring `MAX_FIX_ATTEMPTS` | M |
| E8-F3-T2 | No-progress detection on repeated failure signature | M |
| E8-F3-T3 | Retry prompt assembly: failure report + last diff + plan (never the whole transcript) | M |
| E8-F3-T4 | Per-attempt `FIX_ATTEMPT` events with signature and outcome | S |
| E8-F3-T5 | Tests: pass-first-try, pass-on-attempt-2, exhaust-at-3, early exhaust on no progress | L |

**Acceptance:** a seeded failing repo is driven red → green by the loop; the attempt cap is
never exceeded; identical consecutive failures short-circuit.

---

## E9 — Human Approval Gate & Safety

**Goal:** the guarantee the whole project rests on.

### E9-F1 — Review payload
| Task | Description | Size |
|---|---|---|
| E9-F1-T1 | `ChangeSummaryService` — `change_summary` prompt over the final diff + plan + test evidence | M |
| E9-F1-T2 | `DiffService` — unified diff, per-file add/remove counts, size cap | M |
| E9-F1-T3 | `ApprovalRequest` schema assembling every item in design §9 | M |
| E9-F1-T4 | Risk-note extraction — the agent must state what it was unsure about | M |

### E9-F2 — The gate
| Task | Description | Size |
|---|---|---|
| E9-F2-T1 | `ApprovalService.request()` — create `ApprovalRecord` + token, → `AWAITING_APPROVAL`, emit event | M |
| E9-F2-T2 | `ApprovalService.decide()` — approve/reject, `decided_by`, reason, single-use enforcement | M |
| E9-F2-T3 | Reject path — `REJECTED`, reason persisted, workspace retained, no retry | S |
| E9-F2-T4 | Durable wait: `AWAITING_APPROVAL` survives restart; no timeout auto-approve, ever | M |

### E9-F3 — Safety enforcement & proof
| Task | Description | Size |
|---|---|---|
| E9-F3-T1 | `RemoteOperationGuard` — assert approval before any remote-capable call; raise `ApprovalRequiredError` | M |
| E9-F3-T2 | **Safety test suite** — one test per invariant SI-1…SI-8 | L |
| E9-F3-T3 | Test: `PRService.open_draft_pr()` on a non-approved session raises and performs zero git operations | M |
| E9-F3-T4 | Test: replayed approval token raises `ApprovalAlreadyConsumedError` | S |
| E9-F3-T5 | `docs/SAFETY.md` — the invariants and the test that proves each | M |

**Acceptance:** every invariant has a named failing-if-broken test; no code path reaches a
remote without a persisted approval.

---

## E10 — GitHub Integration & PR Delivery

**Goal:** the only epic allowed to touch a remote — and only after E9 says so.

### E10-F1 — Git operations
| Task | Description | Size |
|---|---|---|
| E10-F1-T1 | `GitService` — branch create, stage, commit (conventional subject + issue ref), push | M |
| E10-F1-T2 | Branch naming `devmind/issue-{n}-{slug}` with collision suffixing | S |
| E10-F1-T3 | Commit authorship/trailers identifying the agent and the approving human | S |

### E10-F2 — PR creation
| Task | Description | Size |
|---|---|---|
| E10-F2-T1 | `PRService.open_draft_pr()` — approval guard first, then `gh pr create --draft` | M |
| E10-F2-T2 | PR body from `pr_body.md`: summary, test evidence, attempts, provenance footer | M |
| E10-F2-T3 | Persist `PullRequestModel`, emit `PR_OPENED`, → `PR_OPENED` state | S |
| E10-F2-T4 | Failure handling: push rejected / no permission / branch exists → `FAILED`, branch retained, no auto-retry | M |

### E10-F3 — Guarantees
| Task | Description | Size |
|---|---|---|
| E10-F3-T1 | Test: PR is created with `--draft`; no merge call exists anywhere in the codebase (grep-asserted) | M |
| E10-F3-T2 | Test: full happy path with a mocked `gh`, asserting exact argv | M |
| E10-F3-T3 | Dry-run mode (`DRY_RUN=true`) logging intended git/gh commands without executing | M |

**Acceptance:** approved sessions produce a draft PR; unapproved sessions cannot, proven by
test; dry-run makes the whole delivery path safe to demo.

---

## E11 — API, Streaming & Operator UX

**Goal:** make a ten-minute autonomous run observable and controllable by a human.

### E11-F1 — REST
| Task | Description | Size |
|---|---|---|
| E11-F1-T1 | `api/sessions.py` — create (202 + background task), get, list with status filter | M |
| E11-F1-T2 | `api/approvals.py` — `GET /approval-request`, `POST /approval` | M |
| E11-F1-T3 | `api/events.py` — paginated history; `GET /diff` as `text/plain` | M |
| E11-F1-T4 | `POST /cancel` — cooperative cancel → `HALTED` | S |
| E11-F1-T5 | Dependency wiring module — one place that composes the object graph | M |

### E11-F2 — Streaming
| Task | Description | Size |
|---|---|---|
| E11-F2-T1 | `GET /stream` — SSE over the event log, `Last-Event-ID` resume, heartbeat | L |
| E11-F2-T2 | Clean disconnect handling; no leaked tasks | M |

### E11-F3 — CLI client
| Task | Description | Size |
|---|---|---|
| E11-F3-T1 | `devmind run <repo> <issue>` — start a session and stream a live `rich` view | L |
| E11-F3-T2 | `devmind approve/reject <session-id>` — renders the review payload, requires explicit typed confirmation | M |
| E11-F3-T3 | `devmind status/logs <session-id>` | S |

**Acceptance:** an operator can start, watch live, review, and approve or reject a run entirely
from the CLI, and reconnect mid-run without losing events.

---

## E12 — Quality, Hardening & Delivery

**Goal:** make it demonstrably production-grade rather than merely finished.

### E12-F1 — Test suite
| Task | Description | Size |
|---|---|---|
| E12-F1-T1 | Shared fixtures: temp workspace, in-memory DB, fake provider, fake sandbox, seeded git repo | L |
| E12-F1-T2 | Coverage gate — ≥ 85% on `services/`, `tools/`, `repositories/`; CI-enforced | M |
| E12-F1-T3 | **End-to-end golden test** — a fixture repo with a seeded bug, driven by a scripted provider through the full state machine to `AWAITING_APPROVAL`, then approved with a mocked `gh` | L |
| E12-F1-T4 | Property tests for the state machine and the path guard | M |

### E12-F2 — Hardening
| Task | Description | Size |
|---|---|---|
| E12-F2-T1 | Graceful shutdown: in-flight sessions checkpointed, not corrupted | M |
| E12-F2-T2 | Resume-after-restart for `AWAITING_APPROVAL` sessions | M |
| E12-F2-T3 | Secret redaction in logs, events, and prompts | M |
| E12-F2-T4 | Workspace retention/cleanup policy with a disk ceiling | M |

### E12-F3 — Delivery
| Task | Description | Size |
|---|---|---|
| E12-F3-T1 | `README.md` — what it is, architecture diagram, quickstart, safety model, honest limitations | L |
| E12-F3-T2 | `Dockerfile` + `docker-compose.yml` (app + Postgres) | M |
| E12-F3-T3 | GitHub Actions CI — ruff, mypy, pytest, coverage gate | M |
| E12-F3-T4 | `docs/DEMO.md` — a reproducible scripted demo, including the rejection path | M |
| E12-F3-T5 | `docs/ADR/` — the load-bearing decisions: manual loop over tool runner, no vector index, two sandbox backends, capability separation over prompt rules | M |

**Acceptance:** CI green on a clean checkout; the e2e golden test proves the whole flow;
README lets a stranger run it in under ten minutes.

---

## Milestones

| Milestone | Epics | Demonstrates |
|---|---|---|
| **M1 — Skeleton** | E1, E2 | Sessions persist and transition; API boots. |
| **M2 — Agent can see** | E3, E4, E5, E6 | Agent reads, searches, edits, and runs commands in a sandbox. |
| **M3 — Agent can work** | E7, E8 | Full autonomous plan → patch → test → self-correct. |
| **M4 — Agent is safe** | E9, E10 | Approval gate proven; draft PR on approval only. |
| **M5 — Production-grade** | E11, E12 | Streaming UX, CI, e2e test, docs. |
