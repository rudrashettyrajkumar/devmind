---
name: devmind-epic-implementation
description: The end-to-end workflow for implementing one DevMind epic from its spec in docs/specs/ — read the spec, plan with a todo list, build bottom-up layer by layer, test as you go, then run the test-runner and standards-auditor subagents before reporting. Use whenever asked to implement, continue, or finish an epic.
---

# Implementing a DevMind Epic

One epic, start to finish, in a repeatable shape.

## 0. Orient (do not skip)

Read, in order:

1. `docs/specs/epic-<nn>-<slug>.md` — the contract for this epic. It is authoritative.
2. `docs/02-epic-breakdown.md` — this epic's tasks and its acceptance criteria.
3. `docs/01-solution-design.md` — only the sections the spec points at.
4. `Claude.md` + the `devmind-standards` skill.

Then check what already exists. **Never rebuild what a prior epic already delivered** —
read the actual code first, and if a dependency epic's output is missing or differs from the
spec, say so before writing code rather than working around it silently.

## 1. Plan

Write a todo list from the spec's task table — one item per task, in dependency order. Keep
exactly one item `in_progress` at a time and close each as it lands. The plan is how a
long-horizon build stays coherent; it is not ceremony.

## 2. Build bottom-up

Always this order. Each layer is complete and typed before the next one starts:

```
enums / constants / exceptions
        ↓
schemas (Pydantic DTOs)          ← define the shape of everything first
        ↓
interfaces (ABCs, if justified)
        ↓
models → repositories            ← all SQLAlchemy stops here
        ↓
services                         ← business logic, constructor injection
        ↓
api routers                      ← thin; translate and delegate
        ↓
tests alongside each layer
```

Working top-down means guessing at shapes you haven't defined yet and refactoring three times.

### While writing

- Consult `devmind-standards` before adding an ABC, a repository, a config flag, or an enum.
  The justification test is not optional.
- Prompts go in `src/devmind/prompts/*.md` — see `devmind-prompt-authoring`. No prompt text in
  a `.py` file.
- Type everything. `mypy --strict` is the bar, and it's cheaper to satisfy while writing than
  to retrofit.
- Write the test with the code, not after the epic. A layer without tests is not done.

## 3. Verify locally

```bash
make check     # ruff + ruff format --check + mypy --strict + pytest
```

Fix everything before moving on. Do not accumulate a debt of failures to clear at the end —
that is how an epic becomes unmergeable.

## 4. Delegate verification

Two subagents, in this order. Both are read-only reviewers; you do the fixing.

1. **`test-runner`** — runs the full suite, reports failures with analysis and the actual
   output. Give it the epic id and any new test paths.
2. **`standards-auditor`** — reviews the diff against `Claude.md`. Give it the epic id and the
   spec path.

Fix everything they report. If you disagree with a finding, say why explicitly rather than
quietly ignoring it — a dismissed finding needs a reason on the record.

Re-run `make check` after fixes.

## 5. Report

Report in this shape, every time:

```
## Epic E<n> — <title> — complete

### Delivered
- E<n>-F1-T1 … <one line each, mapped to the task ids>

### Files
- src/devmind/services/agent_loop.py       (new, 214 lines)
- src/devmind/schemas/agent.py             (new)
- tests/services/test_agent_loop.py        (new, 18 tests)

### Verification
$ make check
ruff: clean · mypy: clean · pytest: 148 passed, 0 failed
coverage: services/ 91%

test-runner:        <summary of its verdict>
standards-auditor:  <summary of its verdict>

### Acceptance criteria
- [x] <criterion from the spec> — <how it was proven>

### Deviations from the spec
- <what changed and why> — or "none"

### Not done / follow-ups
- <anything deferred, with the reason> — or "none"
```

**Then stop.** Do not commit, branch, push, or open a PR unless the human explicitly asks.
Delivery is the `git-pr` subagent's job, and only on request — see `devmind-git-flow`.

## Rules for the whole workflow

- **Finish the epic.** If one task is genuinely blocked, complete every other task in full and
  state plainly what was left and why. Scaling the epic down is the human's call.
- **Report honestly.** If tests fail, show the output. If a criterion is unmet, say so. A green
  report that isn't true costs more than a red one.
- **Deviate deliberately.** If the spec is wrong, say so in a sentence and proceed under a
  stated assumption — don't silently build something else.
- **Never weaken a safety test to make it pass.** A failing test in `tests/safety/` means the
  code broke an invariant. Fix the code, or escalate to the human.
