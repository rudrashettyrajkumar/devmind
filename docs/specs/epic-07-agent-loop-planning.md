# Spec — E7: Agent Loop & Planning

| | |
|---|---|
| **Epic** | E7 |
| **Depends on** | E3, E6 |
| **Blocks** | E8, E9 |
| **Size** | L (~2.5 days) |
| **Skills** | `devmind-standards`, `devmind-prompt-authoring`, `devmind-testing` |

## Purpose

The long-horizon engine: a ReAct loop that plans, acts, observes, and keeps its goal intact
across dozens of steps and a context window that would otherwise overflow. Plus the orchestrator
that drives the state machine from `CREATED` to `TESTING`.

## Design references

`docs/01-solution-design.md` §5 (lifecycle), §6 (loop, context management).

## Contracts

### `AgentContext`

```python
class AgentContext:
    def __init__(self, session_id: str, system_blocks: list[dict[str, object]],
                 tools: list[dict[str, object]], step_budget: int) -> None: ...

    def extend(self, response: LLMResponse, results: list[ToolResultBlock]) -> None:
        """Append the assistant turn verbatim, then ALL tool results as ONE user message."""

    def to_request(self, phase: AgentPhase) -> LLMRequest: ...

    @property
    def estimated_tokens(self) -> int: ...
```

Two rules that are easy to get wrong and expensive to debug:

1. **Append `response.raw_content` unchanged.** Reconstructing the assistant turn from `text`
   drops thinking blocks and breaks continuation.
2. **All tool results go into one user message.** Splitting parallel results across several
   messages teaches the model to stop batching tool calls, and throughput quietly halves.

### `AgentLoop`

```python
class AgentLoop:
    def __init__(self, llm: LLMProvider, executor: ToolExecutor, events: EventRepository,
                 compactor: ContextCompactor, cost: CostCalculator,
                 sessions: SessionRepository) -> None: ...

    async def run(self, ctx: AgentContext, tool_ctx: ToolContext,
                  phase: AgentPhase) -> LoopOutcome: ...
```

Per step, in order:

1. Check cancellation → `LoopOutcome.cancelled()`.
2. Check the session cost ceiling → raise `BudgetExceededError`.
3. `await compactor.compact_if_needed(ctx)`.
4. `response = await llm.complete(ctx.to_request(phase))`.
5. Record usage and cost; emit `LLM_CALL` with tokens and cache-read count.
6. `stop_reason is END_TURN` → `LoopOutcome.completed(response)`.
7. Execute tool calls — concurrently via `asyncio.gather` when there is more than one, since
   the model batches them deliberately.
8. If `finish` was called → `LoopOutcome.completed`.
9. `ctx.extend(response, results)`; increment the step counter.

Budget exhausted → `LoopOutcome.budget_exhausted()`. The caller decides whether that is fatal;
the loop does not decide policy.

```python
class LoopOutcome(BaseModel):
    status: LoopStatus            # COMPLETED | BUDGET_EXHAUSTED | CANCELLED | FAILED
    final_text: str = ""
    steps_used: int = 0
    finish_summary: str | None = None
    confidence: float | None = None
```

### `ContextCompactor`

Four layers, applied cheapest-first (design §6.1):

```python
class ContextCompactor:
    def __init__(self, max_context_tokens: int, threshold: float = 0.7) -> None: ...
    async def compact_if_needed(self, ctx: AgentContext) -> bool: ...
```

1. Tool results are already truncated at execution time (E6).
2. Above `threshold`, enable server-side context editing on the request:
   `context_management={"edits": [{"type": "clear_tool_uses_20250919"}]}` with beta
   `context-management-2025-06-27`. This **clears** old tool results; it does not summarize.
3. Locally drop the bodies of superseded `read_file` results for files that were subsequently
   patched — the current file content is what matters, not what it was six steps ago.
4. **Always re-anchor** after any compaction: append a compact brief with the current todo plan
   and the accumulated diff, so the goal survives context surgery. This is the single most
   important behaviour in the class — an agent that forgets its plan mid-run produces
   confident nonsense.

### `PlannerService`

```python
class PlannerService:
    def __init__(self, llm: LLMProvider, prompts: PromptLoader,
                 todos: TodoRepository, events: EventRepository) -> None: ...

    async def create_plan(self, session: SessionModel, brief: RepoBrief) -> list[TodoItemRead]: ...
```

Renders `planner.md` with the issue and the repo brief. Guards: 2–12 items, each non-empty and
imperative. A plan of one item ("fix the bug") is a planning failure, not a plan — reject and
retry once with an explicit instruction to decompose, then fail the session rather than proceed
with a plan that carries no information.

Plans are persisted and versioned; every update emits `PLAN_UPDATED`.

### `SessionOrchestrator`

```python
class SessionOrchestrator:
    async def run(self, session_id: str) -> None: ...
```

Drives the state machine. Every transition goes through `SessionStateMachine.transition()`,
never a direct status write:

```
CREATED
  → INGESTING      RepoIngestionService.ingest()
  → PLANNING       PlannerService.create_plan()
  → INVESTIGATING  AgentLoop.run(phase=INVESTIGATION, tools=READ_ONLY_TOOLS)
  → EDITING        AgentLoop.run(phase=EDITING,       tools=EDIT_TOOLS)
  → TESTING        handed to E8
```

- **Investigation** gets a read-only tool subset and must end with a findings summary; that
  summary is carried into the editing phase's context.
- **Editing** gets write tools and must produce a non-empty `git diff`. An empty diff after the
  editing phase is a failure, not a success — the agent believing it fixed something without
  changing a file is precisely the failure mode this check exists for.
- Every phase boundary is a checkpoint: state persisted, plan re-anchored, context reset to
  system + brief + plan + prior findings rather than carried whole. Carrying the entire
  investigation transcript into editing is the fastest way to exhaust the window.
- Any `DevMindError` → `FAILED` with `failure_reason`, plus a `SESSION_FAILED` event. Cleanup
  runs in `finally` — a crashed session must not leak a container or a workspace.

## Task plan

E7-F1-T1 … E7-F3-T5. Context and loop first, then planner, then orchestration.

## Testing

All of it against `FakeLLMProvider` — deterministic, no network, no cost.

| Test | Proves |
|---|---|
| `test_agent_loop_basic.py` | Scripted tool call → execution → result appended → `END_TURN` exits |
| `test_agent_loop_message_shape.py` | Assistant turn appended verbatim; **all** parallel results in one user message |
| `test_agent_loop_step_budget.py` | Halts exactly at the budget; returns `BUDGET_EXHAUSTED` |
| `test_agent_loop_cancellation.py` | Cancel flag observed within one step |
| `test_agent_loop_cost_ceiling.py` | `BudgetExceededError` at the ceiling |
| `test_agent_loop_tool_error.py` | A raising tool yields `is_error`; the loop continues |
| `test_context_compactor.py` | Triggers at threshold; plan and diff re-anchored afterwards |
| `test_planner_service.py` | Valid plan persisted; a one-item plan retried then failed |
| `test_orchestrator_happy_path.py` | `CREATED → … → TESTING` with the right transitions in order |
| `test_orchestrator_empty_diff.py` | Editing phase producing no diff → `FAILED` |
| `test_orchestrator_failure.py` | Ingestion error → `FAILED` with reason; cleanup ran |

Assert on `fake_llm.requests` for phase-correct prompts and phase-correct tool subsets — the
request is half the behaviour.

## Acceptance criteria

- [ ] A scripted session runs `CREATED → … → TESTING` deterministically.
- [ ] Parallel tool results arrive in exactly one user message; asserted.
- [ ] Step budget, cost ceiling, and cancellation each halt the loop cleanly.
- [ ] Compaction preserves the plan and the diff; asserted.
- [ ] Investigation cannot write (read-only subset); asserted.
- [ ] An empty diff after editing fails the session.
- [ ] `make check` green.

## Notes

- **No `tool_runner`.** Design §6 records why: per-step events, budgets, checkpointing,
  phase-swapped prompts. Decision made.
- **No multi-agent split.** Design §2 rules it out for v1. One loop with a good plan artifact.
- Cache discipline: the system blocks and tool schemas must be byte-identical across every call
  in a session. Building them once per phase and reusing the object is the way; regenerating
  them per step is the bug.
