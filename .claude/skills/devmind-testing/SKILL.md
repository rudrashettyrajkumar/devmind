---
name: devmind-testing
description: How to write and run tests for DevMind — pytest layout mirroring src, the fake-based determinism strategy (FakeLLMProvider, FakeSandbox), async fixtures, the safety-invariant test suite, coverage gates, and the no-network rule. Use whenever adding tests, running the suite, or diagnosing a failure.
---

# DevMind Testing

## Ground rules

1. **Tests never call a real LLM, a real GitHub, or a real network.** Any test that would is a
   bug in the test. `FakeLLMProvider` and a mocked `gh` cover those seams.
2. **`tests/` mirrors `src/devmind/` exactly.** `src/devmind/services/agent_loop.py` →
   `tests/services/test_agent_loop.py`. Finding a test is never a search.
3. **Every behaviour gets its failure path tested**, not just the happy one. For this project
   the failure paths *are* the product.
4. **Determinism is non-negotiable.** No `sleep`-based timing assumptions, no real clock
   dependence, no test-order coupling. A flaky test gets fixed or deleted the day it flakes.

## Layout

```
tests/
├── conftest.py              # shared fixtures only
├── fakes/
│   ├── fake_llm_provider.py # scripted responses + call recording
│   ├── fake_sandbox.py      # scripted CommandResults
│   └── fake_github.py       # records argv, never executes
├── fixtures/
│   ├── pytest_output/       # recorded real pytest output: pass, fail, error, collect_error
│   └── sample_repo/         # tiny git repo with a seeded bug
├── core/  models/  repositories/  schemas/  services/  tools/  api/
├── safety/                  # one test per invariant SI-1..SI-8
└── e2e/                     # the golden end-to-end run
```

## The fake strategy

`FakeLLMProvider` is the backbone. It is why a nondeterministic system can have a deterministic
test suite.

```python
class FakeLLMProvider(LLMProvider):
    """Returns scripted responses in order and records every request."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("FakeLLMProvider ran out of scripted responses")
        return self._responses.popleft()
```

Helpers to build scripts read like the scenario they describe:

```python
def tool_call(name: str, **kwargs) -> LLMResponse: ...
def final_text(text: str) -> LLMResponse: ...

provider = FakeLLMProvider([
    tool_call("todo_write", items=[...]),
    tool_call("read_file", path="src/calc.py"),
    tool_call("apply_patch", path="src/calc.py", old="a - b", new="a + b"),
    tool_call("run_tests"),
    final_text("Fixed the sign error in add()."),
])
```

Assert on `provider.requests` to verify prompt assembly, cache breakpoints, tool schemas, and
context compaction — the request is as much the output as the response.

## Fixtures worth having in `conftest.py`

| Fixture | Provides |
|---|---|
| `db` | In-memory SQLite engine + `create_all()`, torn down per test |
| `session_repo`, `event_repo`, … | Repositories bound to `db` |
| `workspace` | `tmp_path`-backed workspace with a `WorkspacePathGuard` |
| `sample_repo` | A real `git init`-ed repo with a seeded failing test |
| `fake_llm` | `FakeLLMProvider` factory taking a response script |
| `fake_sandbox` | `FakeSandbox` returning scripted `CommandResult`s |
| `tool_context` | Assembled `ToolContext` for tool unit tests |

Use `pytest_asyncio` with `asyncio_mode = "auto"` so `async def test_...` just works.

## What to test, by layer

| Layer | Focus |
|---|---|
| `core/enums` | Every legal transition; every illegal one raises; terminals are dead ends |
| `repositories/` | Real in-memory SQLite. Event `sequence` integrity under concurrent appends |
| `schemas/` | Validation boundaries, not field echo. Don't test Pydantic itself |
| `tools/` | Happy path, invalid input, path escape, oversized output, sandbox failure |
| `services/` | With fakes. Orchestration order, state transitions, event emission |
| `api/` | `TestClient` + dependency overrides. Status codes and error mapping |
| `safety/` | SI-1…SI-8, one named test each |
| `e2e/` | One golden run, scripted provider, mocked `gh`, real sandbox+DB |

## The safety suite

`tests/safety/` is the most important directory in the repo. Each test names its invariant:

```python
def test_si1_no_registered_tool_can_reach_a_remote(registry: ToolRegistry) -> None:
    """SI-1: the agent has no push/PR/network capability in its object graph."""
    forbidden = {"push", "pr", "pull_request", "remote", "curl", "wget", "http"}
    for tool in registry.all():
        assert not (forbidden & set(tool.name.lower().split("_")))
        source = inspect.getsource(type(tool)).lower()
        assert "git push" not in source
        assert "gh pr" not in source


async def test_si3_open_draft_pr_refuses_without_approval(pr_service, unapproved_session, fake_github):
    """SI-3: PR creation is impossible without a persisted APPROVED record."""
    with pytest.raises(ApprovalRequiredError):
        await pr_service.open_draft_pr(unapproved_session.id)
    assert fake_github.invocations == []      # and it did nothing on the way out
```

A change that breaks a safety test is never "fixed" by editing the test. Fix the code or bring
it to a human.

## Parser tests need real output

`PytestOutputParser` is parsed-text logic, so it gets **recorded fixtures**, not hand-written
approximations:

```
tests/fixtures/pytest_output/
  all_passed.txt   assertion_failure.txt   import_error.txt
  collection_error.txt   timeout_kill.txt   mixed.txt
```

Regenerate them by running pytest against `tests/fixtures/sample_repo` and committing the
output verbatim. Approximated fixtures teach the parser to handle output that doesn't exist.

## Contract tests for parametrised implementations

`Sandbox` has two implementations and one contract, so it gets one shared suite:

```python
@pytest.fixture(params=["subprocess", "docker"])
def sandbox(request) -> Sandbox:
    if request.param == "docker" and not docker_available():
        pytest.skip("docker unavailable")
    return build_sandbox(request.param)
```

Both backends pass the same assertions, or the abstraction is a lie.

## Commands

```bash
make test                       # full suite
pytest tests/services -x -q     # one layer, stop on first failure
pytest -k "self_correction"     # by keyword
pytest --cov=src/devmind --cov-report=term-missing --cov-fail-under=85
pytest tests/safety -v          # the suite that must never be skipped
```

## Coverage

≥ 85% on `services/`, `tools/`, `repositories/`; CI-enforced. Coverage is a floor, not a goal —
100% on getters with the self-correction loop untested is worse than 85% with it covered.

## Reporting a run

When reporting results, always state: **command run, pass/fail counts, and the actual failure
output** for anything red. Never say "tests pass" without having run them in this session.
