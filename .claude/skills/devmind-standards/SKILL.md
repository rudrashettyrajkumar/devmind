---
name: devmind-standards
description: The engineering standards every line of DevMind code must follow — src layout and layer boundaries, Pydantic-everywhere, SQLAlchemy 2.0 behind repositories, ABCs only where they earn their keep, StrEnums over bare strings, Final constants, markdown prompts. Use when writing, reviewing, or refactoring any code in this repo, and whenever deciding whether an abstraction is justified.
---

# DevMind Engineering Standards

Authoritative source: `Claude.md` at the repo root. This skill is the working checklist.
When the two disagree, `Claude.md` wins.

## The one-line philosophy

Full OOP, pragmatically applied. SOLID guides the design; **YAGNI and KISS set the ceiling.**
An abstraction ships only when it has a real second implementation, a real testing boundary,
or a real swap requirement.

## 1. Layers — the dependency rule

```
api/  →  services/  →  repositories/  →  models/
              ↓
        interfaces/ (ABCs)  ·  schemas/ (DTOs)  ·  core/  ·  prompts/  ·  exceptions/
```

Each layer talks **only** to the layer directly below it.

| Never | Instead |
|---|---|
| `api/` imports a SQLAlchemy model | `api/` returns a Pydantic schema built by a service |
| A service imports `Session` from sqlalchemy | The service takes a repository in `__init__` |
| A repository contains an `if status == ...` business rule | The rule lives in the service or on the enum |
| A service raises `HTTPException` | It raises a `DevMindError`; one API handler maps it |
| A router contains a `for` loop over domain objects | That loop is a service method |

**Check before writing any import:** does this import cross a layer boundary downward by
exactly one step? If not, stop.

## 2. Pydantic — no raw dicts crossing a boundary

- Every request/response body is a `BaseModel` in `schemas/`.
- Every tool input is a `BaseModel`; the JSON schema is generated from it with
  `model_json_schema()` — never hand-written, so validation and schema can't drift.
- ORM → schema conversion via `model_config = ConfigDict(from_attributes=True)`.
- Settings via `pydantic-settings`. **Zero `os.environ.get()` calls** outside `core/config.py`.

```python
class TestFailureReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    failed: int
    failures: list[TestFailure]
    signature: str
```

A `dict[str, Any]` in a signature is a code smell. The only legitimate uses are a JSON column
payload and a raw API response about to be parsed.

## 3. SQLAlchemy 2.0 — all of it behind repositories

- `DeclarativeBase`, `Mapped[...]` + `mapped_column(...)`. No legacy `Column()`.
- **`from sqlalchemy.orm import Session` may appear only in `repositories/` and
  `core/database.py`.** Nowhere else. This is grep-checkable and gets checked.
- Sessions come from `DatabaseManager.session_scope()` — a context manager that always closes.
- Repositories expose intention-revealing methods (`get_active_for_repo`), not a generic
  `query()` escape hatch that leaks ORM objects upward.

## 4. ABCs — the justification test

Before writing `class X(ABC)`, answer out loud:

1. Is there a **second implementation shipping in this project**? or
2. Does a test need to substitute it to stay deterministic? or
3. Is there a **named, near-term** swap requirement?

If all three are no → write the plain class. Refactor to an ABC the day the second need
appears, not before.

**Already decided for DevMind (do not re-litigate):**

| ABC | Verdict |
|---|---|
| `LLMProvider` | ✅ `AnthropicProvider` + `FakeLLMProvider` |
| `Sandbox` | ✅ `DockerSandbox` + `SubprocessSandbox` |
| `Tool` | ✅ ten-plus implementations behind a registry |
| `GitHubClient` | ❌ one implementation — plain class, mocked in tests |
| `TestOutputParser` | ❌ **for now** — extract when a non-pytest parser is actually needed |
| Repositories | ✅ Session, Event, Approval — real testing boundary |

## 5. Full OOP, no loose scripts

- Logic lives in a class. Constructor injection — dependencies arrive via `__init__`, never
  grabbed from module globals or a singleton.
- **No `utils.py`.** Group related behaviour into a named class (`OutputTruncator`,
  `WorkspacePathGuard`, `CostCalculator`), not five unrelated free functions.
- A module-level function is acceptable only for a genuinely pure, stateless helper used in
  one place. If it needs configuration, it wants to be a class.

```python
class SelfCorrectionController:
    def __init__(self, parser: PytestOutputParser, runs: TestRunRepository,
                 max_attempts: int = MAX_FIX_ATTEMPTS) -> None:
        self._parser = parser
        self._runs = runs
        self._max_attempts = max_attempts
```

## 6. Enums — no bare strings for closed sets

Any fixed set of values is a `StrEnum` in `core/enums.py`. Behaviour that belongs to the value
lives **on the enum**:

```python
class SessionStatus(StrEnum):
    CREATED = "created"
    AWAITING_APPROVAL = "awaiting_approval"
    PR_OPENED = "pr_opened"
    REJECTED = "rejected"

    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES

    def can_transition_to(self, target: "SessionStatus") -> bool:
        return target in _LEGAL_TRANSITIONS[self]
```

A string literal comparison against a status is a bug waiting to happen. `== "aproved"` is
silent; `SessionStatus.APROVED` is an error at import.

## 7. Constants — nothing meaningful inline

`core/constants.py`, everything `Final`. Any literal used more than once, or any literal that
could plausibly change, lives there.

```python
MAX_FIX_ATTEMPTS: Final[int] = 3
MAX_TOOL_RESULT_CHARS: Final[int] = 20_000
SANDBOX_COMMAND_TIMEOUT_SECONDS: Final[int] = 300
ALLOWED_COMMAND_BINARIES: Final[frozenset[str]] = frozenset({"python", "pytest", "uv", "pip", "ruff", "mypy", "git"})
```

Business logic references `MAX_FIX_ATTEMPTS`, never a bare `3`.

**Rule of thumb:** a tunable knob goes in `Settings`; a fixed engineering constant goes in
`constants.py`. If an operator would ever want to change it per-deployment, it's config.

## 8. Prompts — markdown, never Python strings

One `.md` per prompt in `src/devmind/prompts/`, YAML frontmatter + markdown body, loaded by
`PromptLoader`. A triple-quoted prompt in a `.py` file is a review-blocking defect.
See the `devmind-prompt-authoring` skill.

## 9. Anti-over-engineering — apply literally

- No ABC for a single implementation with no planned second.
- No repository for a one-off table touch.
- No enum for a value used once with no typo risk.
- No config flag for something that will never change.
- No queue, cache, or service split "for scale later."
- **If you're adding an abstraction to satisfy a rule in this document rather than a need in
  the code, stop and write the plain version.**

## 10. Types & errors

- `mypy --strict` clean. No bare `Any`; no unexplained `# type: ignore` (needs a reason
  comment).
- Modern syntax: `X | None`, `list[str]`, `dict[str, int]`.
- Custom exceptions from `DevMindError`. Never `raise Exception(...)`, never a bare `except:`.
- Catch a **chain**, not one broad class — most specific first.
- Async all the way down for I/O. Blocking work (subprocess, Docker) goes through a thread
  executor so it never stalls the loop.

## 11. Pre-commit self-review

Run this list before declaring any task done:

- [ ] Every new payload is a Pydantic model, not a dict.
- [ ] No `Session` import outside `repositories/` or `core/database.py`.
- [ ] Every new closed-set value is a `StrEnum`.
- [ ] Every repeated literal is a `Final` in `constants.py`.
- [ ] Every new ABC passes the §4 justification test.
- [ ] No prompt text in a `.py` file.
- [ ] No `utils.py`; no module-level mutable state.
- [ ] `ruff check`, `ruff format --check`, `mypy --strict` all clean.
- [ ] New behaviour has tests, including its failure path.
- [ ] No literal `3`, `0.75`, or model name typed inline anywhere.
