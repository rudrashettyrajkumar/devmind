# Spec — E8: Test Execution & Self-Correction

| | |
|---|---|
| **Epic** | E8 |
| **Depends on** | E5, E7 |
| **Blocks** | E9 |
| **Size** | L (~2.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

The feedback loop that makes autonomy real. The agent's belief that it fixed the bug is
worthless; the test suite is the oracle. This epic runs the suite, reads the failure properly,
and decides — within a hard budget — whether another attempt is worth making.

## Design references

`docs/01-solution-design.md` §8 (self-correction), §16 (no test suite, already-red baseline).

## Contracts

### `TestExecutionService`

```python
class TestExecutionService:
    def __init__(self, sandbox: Sandbox, parser: PytestOutputParser,
                 runs: TestRunRepository, events: EventRepository) -> None: ...

    async def run_baseline(self, session_id: str, profile: RepoProfile) -> TestRunResult: ...
    async def run(self, session_id: str, profile: RepoProfile, *, attempt: int,
                  node_ids: list[str] | None = None,
                  keyword: str | None = None) -> TestRunResult: ...
```

Command assembly from `RepoProfile.test_command`, plus `-q --tb=short -p no:cacheprovider` and
`--timeout` if `pytest-timeout` is available. `node_ids` / `-k` narrow a targeted re-run.

Every run persists a `TestRunModel` and emits a `TEST_RUN` event: attempt, baseline flag,
counts, signature, duration.

**Baseline discipline.** Before any edit, run the full suite on the clean checkout and record
which tests were already failing. Those are excluded from the verdict. Without this the agent
gets blamed for a broken `main` — and, worse, might "fix" unrelated pre-existing failures and
balloon the diff.

**No test suite.** `profile.has_test_suite is False` → skip execution, mark the session
`UNVERIFIED`, and proceed. E9 must surface that prominently in the approval payload; an
unverified change is exactly what a human needs to know before approving.

### `PytestOutputParser`

A plain class, not an ABC — one implementation, and `Claude.md` §9 says extract the abstraction
when a second parser actually exists.

```python
class PytestOutputParser:
    def parse(self, result: CommandResult) -> TestFailureReport: ...
```

Must handle, distinctly:

| Case | Signal |
|---|---|
| All passed | `=== N passed in Xs ===` |
| Assertion failures | `FAILED path::test - message` + the `_____ test _____` blocks |
| Errors (fixture/setup) | `ERROR path::test` |
| Collection errors | `ERRORS` / `!!! Interrupted: N error during collection !!!` |
| Import errors | `ModuleNotFoundError` / `ImportError` during collection |
| Timeout / kill | `result.timed_out` — no parseable output at all |
| Unparseable | Non-zero exit with no recognisable summary |

The last two matter more than they look. A killed run produces no pytest summary, and a parser
that returns "0 failures" for it will convince the controller everything passed.

```python
class TestFailure(BaseModel):
    node_id: str
    file: str | None
    line: int | None
    exception_type: str | None
    message: str
    traceback: str            # trimmed to the frames inside the repo

class TestFailureReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int; passed: int; failed: int; errors: int; skipped: int
    failures: list[TestFailure]
    collection_error: str | None = None
    timed_out: bool = False
    unparseable: bool = False
    signature: str
    truncated_output: str

    @property
    def succeeded(self) -> bool:
        return (self.failed == 0 and self.errors == 0
                and not self.timed_out and not self.unparseable
                and self.collection_error is None)
```

**The signature** is what makes no-progress detection possible:

```python
signature = sha256("|".join(sorted(f"{f.node_id}:{f.exception_type}" for f in failures)))
```

Node ids plus exception types, sorted — stable across runs, insensitive to ordering and to
line-number drift, sensitive to a genuinely different failure.

### `SelfCorrectionController`

```python
class SelfCorrectionController:
    def __init__(self, runs: TestRunRepository, events: EventRepository,
                 max_attempts: int = MAX_FIX_ATTEMPTS) -> None: ...

    def decide(self, session_id: str, report: TestFailureReport,
               attempt: int) -> CorrectionDecision: ...
```

```python
class CorrectionDecision(BaseModel):
    action: CorrectionAction        # SUCCEEDED | RETRY | EXHAUSTED
    reason: str
    attempts_remaining: int
```

Decision order:

1. `report.succeeded` → `SUCCEEDED`.
2. `attempt >= max_attempts` → `EXHAUSTED` ("attempt budget spent").
3. `signature == previous_signature` → `EXHAUSTED` ("no progress: identical failure signature").
4. Otherwise → `RETRY`.

Rule 3 is the interesting one. An identical signature means the last edit changed nothing that
mattered; spending the third attempt re-deriving the same wrong hypothesis is waste. Escalate
to a human instead, and say why.

### The retry prompt

`test_failure_analysis.md`, rendered with **only**: the failure report, the last diff, the todo
plan, the attempt number, and the max. **Not** the whole investigation transcript. A focused
retry prompt outperforms a huge one, and it keeps context available for the actual fix.

Then the orchestrator re-enters the editing phase with that context and transitions
`TESTING → EDITING`, incrementing `fix_attempts`, emitting `FIX_ATTEMPT` with the signature and
the decision.

### Orchestrator integration

```
TESTING ─► run tests ─► parse ─► decide
                                  │
              SUCCEEDED ──────────┴──► SUMMARIZING
              RETRY ──────────────────► EDITING (attempt += 1)
              EXHAUSTED ──────────────► EXHAUSTED (terminal)
```

`EXHAUSTED` is terminal and honest: DevMind could not verify a fix, so no PR is offered. It does
not fall through to the approval gate with a shrug. The session record keeps every attempt for
a human to read.

Before entering `SUMMARIZING`, run the **full** suite once even if the last run was targeted —
green on three tests is not green.

## Task plan

E8-F1-T1 … E8-F3-T5. Parser first (it is the deepest work and everything downstream depends on
its shape), then execution, then the controller.

## Testing

**Recorded fixtures, not hand-written approximations.** Generate real pytest output against
`tests/fixtures/sample_repo` and commit it verbatim to
`tests/fixtures/pytest_output/`: `all_passed.txt`, `assertion_failure.txt`, `multiple_failures.txt`,
`import_error.txt`, `collection_error.txt`, `fixture_error.txt`, `empty_suite.txt`. An
approximated fixture teaches the parser to handle output that does not exist.

| Test | Proves |
|---|---|
| `test_pytest_parser.py` | Each fixture parses to the right counts, node ids, and messages |
| `test_pytest_parser_edge_cases.py` | Timeout → `timed_out`; garbage → `unparseable`; **neither reports success** |
| `test_failure_signature.py` | Stable across re-runs; changes when failures change; order-insensitive |
| `test_test_execution_service.py` | Argv assembly; targeted re-run; persistence; `TEST_RUN` emitted |
| `test_baseline.py` | Pre-existing failures excluded from the verdict |
| `test_no_test_suite.py` | Session marked `UNVERIFIED`, run skipped, flow continues |
| `test_self_correction_controller.py` | Pass first try; pass on attempt 2; exhaust at 3; **early exhaust on repeated signature** |
| `test_correction_integration.py` | Seeded failing repo driven red → green through the orchestrator |

The integration test is the epic's proof: a fixture repo with a deliberate bug, a scripted
provider that fixes it on attempt 2, and assertions on the state path
`TESTING → EDITING → TESTING → SUMMARIZING`.

## Acceptance criteria

- [ ] A seeded failing repo is driven red → green by the loop.
- [ ] `MAX_FIX_ATTEMPTS` is never exceeded; asserted.
- [ ] An identical consecutive signature short-circuits to `EXHAUSTED`.
- [ ] Timeouts and unparseable output never report success.
- [ ] Pre-existing failures are excluded from the verdict.
- [ ] A repo with no tests proceeds as `UNVERIFIED`, not as passing.
- [ ] A full suite run precedes `SUMMARIZING`.
- [ ] `make check` green.

## Notes

- **Do not** introduce a `TestOutputParser` ABC yet (`Claude.md` §9). One implementation.
  Extract it the day a JS parser exists.
- Never let the agent edit a test to make it pass. Add a guard: if the diff touches only files
  under `profile.test_paths` while the issue is a bug report, flag it loudly in the approval
  payload. This is the single most common way an autonomous coding agent produces a green,
  worthless PR.
- `MAX_FIX_ATTEMPTS` is read from settings (defaulting to the constant), never typed inline.
