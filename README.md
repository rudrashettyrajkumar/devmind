# DevMind

> An autonomous long-horizon coding agent. Give it a GitHub issue and a repository; it plans,
> investigates, patches, runs the tests, and recovers from its own failures — then **stops and
> waits for a human** before anything leaves the machine.

**Status: design and planning complete. Implementation not started.**

This repository currently contains the full solution design, the epic breakdown, per-epic
implementation specs, and the Claude Code skills and subagents that will build it.

---

## The idea

A scoped-down version of the architecture behind Devin and OpenHands, built to a strict
engineering standard. The interesting problems are not "call an LLM with tools" — they are:

- **Long horizon.** Dozens of tool calls across many minutes without losing the plan or
  overflowing context.
- **Verification.** The agent's belief that it fixed the bug is worthless; the test suite is the
  oracle, and it runs in a sandbox.
- **Recovery.** Tests fail on the first attempt. The agent reads the failure, forms a new
  hypothesis, and retries — within a hard budget, with detection for when it is going in circles.
- **Containment.** The agent has no ability to push, open a PR, or reach the network. Not because
  it was told not to — because the capability does not exist in its object graph.

## The safety model, in one paragraph

The agent's tool registry contains no tool that can reach a remote. The sandbox runs with
networking disabled and no inherited credentials. `PR_OPENED` is reachable in the state machine
only from `APPROVED`, and `APPROVED` only through an explicit human decision that names the
human. `PRService.open_draft_pr()` re-reads the approval record from the database before doing
anything and refuses without it. PRs are always drafts; no merge code path exists. Eight
invariants, each with a named test that fails if it breaks.

## Documents

| Document | What it is |
|---|---|
| [`docs/01-solution-design.md`](docs/01-solution-design.md) | Architecture, safety invariants, state machine, agent loop, context strategy, data model, API, risks |
| [`docs/02-epic-breakdown.md`](docs/02-epic-breakdown.md) | 12 epics → features → tasks, with dependencies, sizes, and acceptance criteria |
| [`docs/specs/`](docs/specs/) | One implementation spec per epic — contracts, code shapes, test plans |
| [`docs/03-build-prompts.md`](docs/03-build-prompts.md) | Copy-paste build prompt per epic, naming its spec, skills, and review subagents |
| [`Claude.md`](Claude.md) | The engineering standards every line of code must follow |

## Build assets

**Skills** (`.claude/skills/`)

| Skill | Purpose |
|---|---|
| `devmind-standards` | Layer boundaries, Pydantic-everywhere, justified abstractions, enums, constants |
| `devmind-testing` | Test layout, the fake-based determinism strategy, the safety suite, coverage |
| `devmind-git-flow` | Branch naming, conventional commits, the human-approval rule, PR template |
| `devmind-epic-implementation` | The workflow: orient → plan → build bottom-up → verify → report |
| `devmind-prompt-authoring` | Frontmatter schema and Claude Opus 5 prompting conventions |

**Subagents** (`.claude/agents/`)

| Agent | Purpose |
|---|---|
| `spec-implementer` | Implements one epic from its spec, in an isolated context |
| `test-runner` | Runs the suite, lint, and types; reports failures with analysis. Read-only |
| `standards-auditor` | Audits the diff against `Claude.md` — both violations and over-application |
| `git-pr` | Branch, commit, push, draft PR. Requires explicit human authorisation |

## Planned architecture

```
api/         FastAPI routers — HTTP only
services/    SessionOrchestrator · AgentLoop · PlannerService · SelfCorrectionController
             TestExecutionService · ApprovalService · PRService · AnthropicProvider
tools/       read_file · search_code · apply_patch · run_tests · todo_write · … (no network)
repositories/  all SQLAlchemy lives here
models/ schemas/ interfaces/ core/ prompts/ exceptions/
             ↓
    Sandbox (Docker | subprocess)   LLMProvider (Anthropic | fake)
```

## Planned stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Anthropic SDK (`claude-opus-5`) ·
Docker / subprocess sandbox · pytest · ruff · mypy --strict

## Scope, stated honestly

**In:** Python repositories with a pytest suite; small, well-specified bugs and features;
single-process operation; a REST + SSE API and a CLI.

**Out (deliberately):** multi-agent orchestration, vector code indexing, multi-language build
matrices, a web UI, auto-merge — and any form of auto-approval, ever.

## Getting started

The build is driven from [`docs/03-build-prompts.md`](docs/03-build-prompts.md) — one epic at a
time, each verified by the `test-runner` and `standards-auditor` subagents before the next
begins.
