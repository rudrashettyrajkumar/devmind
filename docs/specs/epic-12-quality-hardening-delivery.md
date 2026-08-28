# Spec — E12: Quality, Hardening & Delivery

| | |
|---|---|
| **Epic** | E12 |
| **Depends on** | all |
| **Blocks** | — |
| **Size** | L (~2.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing`, `devmind-git-flow` |

## Purpose

Turn a working system into a demonstrably production-grade one. The end-to-end golden test and
the README are the two artifacts by which this project will actually be judged.

## Contracts

### The end-to-end golden test

The single most valuable test in the repository. It proves the whole thesis.

```
tests/e2e/test_full_session.py
tests/fixtures/sample_repo/          # a real git repo with a seeded bug
  pyproject.toml
  src/calc/operations.py             # subtract() used where add() belongs
  tests/test_operations.py           # one test fails on HEAD
```

The test:

1. Creates a session against the fixture repo (local path, no network).
2. Runs the orchestrator with a **scripted `FakeLLMProvider`** — plan, investigate, patch
   wrongly, test (fail), read the failure, patch correctly, test (pass), summarize.
3. Asserts the state path exactly:
   `CREATED → INGESTING → PLANNING → INVESTIGATING → EDITING → TESTING → EDITING → TESTING → SUMMARIZING → AWAITING_APPROVAL`.
4. Asserts the session **stops** at `AWAITING_APPROVAL` and that no git remote operation
   occurred.
5. Approves via `ApprovalService` with a named human.
6. Opens the PR with a mocked `gh`, asserting `--draft` and the exact argv.
7. Asserts `PR_OPENED`, the approval consumed, and the event log replayable in order.

It uses the **real** sandbox (subprocess), the **real** database (in-memory), the real state
machine, real tools, and real parsers. Only the LLM and `gh` are faked — everything the project
claims to do is actually exercised.

A second variant asserts the rejection path: reject → `REJECTED`, reason persisted, zero git
operations, workspace retained.

### Coverage

```toml
[tool.coverage.report]
fail_under = 85
```

Enforced on `services/`, `tools/`, `repositories/`. Coverage is a floor: 100% on getters with
the self-correction loop untested is worse than 85% with it covered. Report per-package numbers
so a thin spot can't hide behind an average.

### Property tests

Two places where exhaustive beats example-based:

- **State machine.** Over the cartesian product of statuses: a transition succeeds iff it is in
  the legal map; no sequence of legal transitions ever reaches `PR_OPENED` without passing
  through `APPROVED`.
- **Path guard.** Generated path strings — random `..` sequences, absolute paths, unicode,
  null bytes, long names — never resolve outside the workspace root.

### Hardening

| Item | Requirement |
|---|---|
| Graceful shutdown | SIGTERM → stop accepting sessions, checkpoint in-flight ones to their last completed phase, tear down sandboxes, exit. No half-applied state. |
| Restart recovery | On boot, `AWAITING_APPROVAL` sessions are re-listed and decidable. Sessions in a running state at boot are marked `FAILED` with "interrupted by restart" — never silently resumed mid-phase. |
| Secret redaction | A `SecretRedactor` applied to logs, event payloads, and anything entering a prompt. Patterns: `sk-ant-`, `ghp_`, `github_pat_`, `AKIA`, bearer tokens, `.env` contents. |
| Workspace retention | Retain on `REJECTED`, `FAILED`, `EXHAUSTED` (a human will want to look); clean on `PR_OPENED` after N days. Disk ceiling enforced; oldest cleaned first. |
| Sandbox leak check | A test asserting no container survives a failed session. |

### Delivery

**`README.md`** — the front door. Must contain:
- What DevMind is, in three sentences, and honestly: a scoped autonomous coding agent, not Devin.
- The architecture diagram from the solution design.
- Quickstart: install, `.env`, run, first session — under ten minutes for a stranger.
- **The safety model, prominently** — the approval gate, the invariants, and where the tests are.
- **Honest limitations**: Python/pytest only; subprocess sandbox is not a security boundary;
  scoped to small, well-specified issues; no vector index; single process.
- Cost expectations for a typical session.

A README that oversells is worse than no README. The honesty section is what makes the rest
credible.

**`Dockerfile`** — multi-stage, non-root, `uv sync --frozen`.
**`docker-compose.yml`** — app + Postgres + a mounted workspace volume.

**CI** (`.github/workflows/ci.yml`):
```yaml
jobs: [lint (ruff), typecheck (mypy --strict), test (pytest + coverage gate), safety (pytest tests/safety -v)]
```
The safety job runs separately so its failure is unmissable in the checks list.

**`docs/DEMO.md`** — a reproducible script: seed a repo with a known bug, run a session, show
the live stream, show the review payload, approve, show the draft PR. Include the rejection path
— a demo that only shows the happy path is not demonstrating the safety model.

**`docs/ADR/`** — one page each for the load-bearing decisions, so the next reader understands
the *why* without reverse-engineering it:
1. Manual agent loop over the SDK `tool_runner`.
2. No vector index — ripgrep and an AST symbol map.
3. Two sandbox backends and the honest limits of each.
4. Capability separation over prompt-level rules for the approval gate.
5. `create_all()` over Alembic for v1.

## Task plan

E12-F1-T1 … E12-F3-T5. Fixtures → e2e → coverage → property tests → hardening → docs → CI.

## Acceptance criteria

- [ ] The e2e golden test passes and covers the full flow including one real self-correction.
- [ ] The rejection variant passes: zero git operations, workspace retained.
- [ ] Coverage ≥ 85% on `services/`, `tools/`, `repositories/`; CI-enforced.
- [ ] CI green on a clean checkout, with the safety job separate.
- [ ] Graceful shutdown leaves no corrupt state and no leaked sandbox.
- [ ] Secrets never appear in logs, events, or prompts; asserted.
- [ ] README lets a stranger run it in under ten minutes and states the limitations plainly.
- [ ] `docker compose up` works.
- [ ] All five ADRs written.
- [ ] `make check` green.

## Notes

- Resist adding features here. This epic is about proving what exists, not extending it.
- If the e2e test is hard to write, that is information about the design — take it seriously
  rather than working around it with mocks.
- The rejection-path test matters as much as the happy path. The claim is "it stops when a
  human says no", and an untested claim is a marketing line.
