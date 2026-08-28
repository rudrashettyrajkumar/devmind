# DevMind — Build Prompts

Copy-paste prompts, one per epic, in order. Each names the spec, the skills, and the subagents
to use. Run them in sequence — every epic assumes its dependencies are built and green.

## How to use this file

1. Start a fresh Claude Code session in the repo root (a long build in one context loses fidelity).
2. Paste the prompt for the next epic verbatim.
3. When it reports done, read the report — especially the **Deviations** and **Not done**
   sections. Do not move on over a red `make check`.
4. Commit the epic (prompt at the bottom of this file) before starting the next.

**The assets**

| Skill | Use |
|---|---|
| `devmind-standards` | The coding rules. Every epic. |
| `devmind-testing` | Test layout, fakes, fixtures, coverage. Every epic. |
| `devmind-epic-implementation` | The workflow: orient → plan → build bottom-up → verify → report. Every epic. |
| `devmind-prompt-authoring` | Authoring `prompts/*.md`. E3, E7, E8, E9, E10. |
| `devmind-git-flow` | Branching, commits, PRs. Delivery only. |

| Subagent | Use |
|---|---|
| `spec-implementer` | Implements an epic in an isolated context (optional — see below). |
| `test-runner` | Runs the suite and reports failures with analysis. After every epic. |
| `standards-auditor` | Audits the diff against `Claude.md`. After every epic. |
| `git-pr` | Branch, commit, push, draft PR. **Only when you explicitly ask.** |

> **On `spec-implementer`:** the prompts below implement directly in the main session, which is
> usually what you want — you can see the work and steer it. Delegate to `spec-implementer`
> instead when you want the epic built in a clean context and only the report back. Either way,
> `test-runner` and `standards-auditor` run afterwards.

---

## E1 — Foundation & Project Skeleton

```
Implement Epic E1 (Foundation & Project Skeleton) for DevMind.

Use the devmind-epic-implementation skill as your workflow and the devmind-standards
skill for every coding decision.

Spec:      docs/specs/epic-01-foundation-and-skeleton.md
Tasks:     docs/02-epic-breakdown.md, section E1
Standards: Claude.md
Design:    docs/01-solution-design.md sections 14 and 17

Build the complete src-layout skeleton: pyproject.toml with ruff and mypy --strict
config, the full package tree, Settings via pydantic-settings, constants.py with
everything Final, enums.py, the DevMindError hierarchy, LoggingConfigurator, the
FastAPI application factory with lifespan, /health, and the RFC-7807 error handler.
Write tests alongside per the devmind-testing skill.

Two constraints from the spec that are easy to miss:
- No abstract base classes in this epic. Nothing has two implementations yet.
- SandboxBackend.AUTO must resolve cleanly to SUBPROCESS with a logged warning —
  this dev machine has no Docker and that is the default developer path.

When make check is green, invoke the test-runner subagent to verify the suite, then
the standards-auditor subagent to audit against Claude.md. Fix everything they report
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit or create a branch.
```

---

## E2 — Session Domain & Persistence

```
Implement Epic E2 (Session Domain & Persistence) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, and devmind-testing for the tests.

Spec:   docs/specs/epic-02-session-domain-persistence.md
Tasks:  docs/02-epic-breakdown.md, section E2
Design: docs/01-solution-design.md sections 5 and 11

E1 is complete — read the existing code first and build on it; do not recreate it.

Build the SQLAlchemy 2.0 models (DeclarativeBase, Mapped[...]), DatabaseManager with
session_scope(), all six repositories, the Pydantic schemas, and the SessionStateMachine
with its complete legal-transition map.

Non-negotiable from the spec:
- sqlalchemy.orm.Session may be imported ONLY in repositories/ and core/database.py.
- EventRepository.append must allocate sequence atomically; prove it with a concurrent
  test.
- The illegal-transition test must be generated over the full cartesian product of
  statuses, so adding a status without updating the map fails the suite.
- PR_OPENED must be reachable only from APPROVED. Assert it structurally.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
they report and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E3 — LLM Provider & Prompt System

```
Implement Epic E3 (LLM Provider & Prompt System) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-prompt-authoring for every prompt file, and devmind-testing
for the tests.

Spec:   docs/specs/epic-03-llm-provider-prompt-system.md
Tasks:  docs/02-epic-breakdown.md, section E3
Design: docs/01-solution-design.md sections 6.1, 13, 15

E1 and E2 are complete — read them first.

Build the LLMProvider ABC, the LLM schemas, AnthropicProvider, FakeLLMProvider with its
script builders, the CostCalculator, the PromptLoader, and all seven prompt markdown
files.

Current-API facts the spec depends on — getting these wrong is a 400 or a silent
quality loss:
- model claude-opus-5, thinking={"type": "adaptive"}, effort inside output_config
- NO temperature, top_p, top_k, budget_tokens, or assistant prefill anywhere
- error handling is a most-specific-first chain, not one broad except
- cache_control goes on the LAST system block; no volatile value may appear in any
  system block
- append response.raw_content back verbatim on the next turn

Every prompt goes in src/devmind/prompts/*.md with validated frontmatter. Include the
test that greps src/ for prompt-shaped string literals and fails on a hit.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E4 — Workspace & Repository Ingestion

```
Implement Epic E4 (Workspace & Repository Ingestion) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-testing for the tests.

Spec:   docs/specs/epic-04-workspace-repo-ingestion.md
Tasks:  docs/02-epic-breakdown.md, section E4
Design: docs/01-solution-design.md sections 3 (SI-5) and 10

E1-E3 are complete — read them first.

Build WorkspacePathGuard, WorkspaceManager, RepoIngestionService, GitHubClient (issue
reads only), RepoProfile detection, CodeIndexService, SymbolIndexer, RepoBrief, and
CodeSearchService.

Build WorkspacePathGuard FIRST and test it adversarially — it is the sole enforcement
of safety invariant SI-5. It must reject ../ traversal, absolute paths, symlinks
pointing out of the workspace, and symlinked directories. Path.resolve() then
is_relative_to(root) — never string prefix matching.

Also from the spec:
- This epic uses gh for READS ONLY. No branch, no push, no PR code exists yet.
- Never import or execute the target repository's code. Static AST analysis only.
- No vector index — ripgrep plus an AST symbol map (design section 2).
- RepoBrief must be deterministic for a fixed commit; it lives in the cached prefix.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E5 — Sandbox Execution Layer

```
Implement Epic E5 (Sandbox Execution Layer) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-testing for the tests.

Spec:   docs/specs/epic-05-sandbox-execution.md
Tasks:  docs/02-epic-breakdown.md, section E5
Design: docs/01-solution-design.md sections 3 (SI-2, SI-8) and 7

E1-E4 are complete — read them first.

Build the Sandbox ABC, SandboxCommand/CommandResult schemas, CommandAllowlist,
OutputTruncator, SubprocessSandbox, DockerSandbox, and SandboxFactory.

Enforcement points from the spec:
- argv lists only. No shell=True anywhere in this codebase, ever.
- The sandbox environment is built from an allowlist and must NOT inherit host
  credentials: force GIT_TERMINAL_PROMPT=0, GIT_ASKPASS=/bin/false, and blank
  GH_TOKEN / GITHUB_TOKEN / ANTHROPIC_API_KEY. Assert this in a test.
- Timeout kills the whole process group; assert no orphan survives.
- OutputTruncator keeps head AND tail — pytest's summary is at the end and the
  self-correction loop needs it.
- Docker gets --network=none; the subprocess backend must document honestly that it
  is process isolation, not a security boundary.

Write ONE parametrised contract suite both backends pass. This machine has no Docker,
so those tests must skip with a stated reason — and a skipped suite is never reported
as a passing one.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E6 — Tool Framework & Tool Suite

```
Implement Epic E6 (Tool Framework & Tool Suite) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-testing for the tests.

Spec:   docs/specs/epic-06-tool-framework.md
Tasks:  docs/02-epic-breakdown.md, section E6
Design: docs/01-solution-design.md sections 3 (SI-1) and 6.2

E1-E5 are complete — read them first.

Build the Tool ABC, ToolRegistry with subset(), ToolExecutor, ToolContext, and all
eleven tools: list_dir, read_file, search_code, find_symbol, write_file, apply_patch,
run_command, run_tests (thin shell — E8 fills it in), git_diff, todo_write, finish.

This epic is where safety invariant SI-1 becomes structural. From the spec:
- The registry must contain NO tool that can reach a remote. Write the SI-1 test that
  greps every registered tool's source for "git push", "gh pr", urlopen, requests.,
  httpx. and fails on any hit.
- Every path-taking tool goes through WorkspacePathGuard. Parametrise the escape test
  across every such tool.
- Do NOT add a generic bash tool. Dedicated typed tools plus one allowlisted
  run_command — a shell would erase SI-1 and SI-8 in a single commit.
- ToolExecutor catches EVERYTHING into an is_error result. A tool error is information
  the agent reads, never an exception that kills a recoverable session.
- apply_patch must fail loudly on 0 or >1 matches, with a message telling the model how
  to succeed next time.
- to_api_schemas() must be byte-stable across calls — it sits in the cached prefix.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E7 — Agent Loop & Planning

```
Implement Epic E7 (Agent Loop & Planning) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-prompt-authoring if you touch any prompt, devmind-testing
for the tests.

Spec:   docs/specs/epic-07-agent-loop-planning.md
Tasks:  docs/02-epic-breakdown.md, section E7
Design: docs/01-solution-design.md sections 5 and 6

E1-E6 are complete — read them first.

Build AgentContext, AgentLoop, ContextCompactor, PlannerService, and SessionOrchestrator
driving CREATED through TESTING.

The two loop rules that are easy to get wrong and expensive to debug:
- Append response.raw_content UNCHANGED. Reconstructing the assistant turn from text
  drops thinking blocks and breaks continuation.
- ALL parallel tool results go into ONE user message. Splitting them teaches the model
  to stop batching and throughput quietly halves. Assert this in a test.

Also from the spec:
- Investigation phase gets a READ-ONLY tool subset via registry.subset(). The agent
  cannot edit before it has understood anything — that is structural, not a prompt rule.
- The editing phase must produce a non-empty diff; an empty diff is a FAILED session.
- ContextCompactor must ALWAYS re-anchor the plan and diff after compacting. An agent
  that forgets its plan mid-run produces confident nonsense.
- Step budget, cost ceiling, and cancellation each halt the loop cleanly.
- No tool_runner and no multi-agent split — both decided in design section 6 and 2.

Everything is tested against FakeLLMProvider. Assert on fake_llm.requests for
phase-correct prompts and tool subsets.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E8 — Test Execution & Self-Correction

```
Implement Epic E8 (Test Execution & Self-Correction) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-prompt-authoring for the retry prompt, devmind-testing for
the tests.

Spec:   docs/specs/epic-08-test-execution-self-correction.md
Tasks:  docs/02-epic-breakdown.md, section E8
Design: docs/01-solution-design.md section 8

E1-E7 are complete — read them first.

Build TestExecutionService, PytestOutputParser, TestFailureReport with its stable
signature, and SelfCorrectionController. Wire TESTING into the orchestrator with the
retry loop.

Build the parser FIRST — it is the deepest work and everything downstream depends on
its shape. Generate REAL pytest output against tests/fixtures/sample_repo and commit it
verbatim to tests/fixtures/pytest_output/. Approximated fixtures teach the parser to
handle output that does not exist.

From the spec:
- A timed-out or unparseable run must NEVER report success. That failure mode would
  convince the controller everything passed.
- Run a baseline before any edit and exclude pre-existing failures from the verdict.
- No test suite → mark the session UNVERIFIED and proceed; do not report it as passing.
- The signature is sha256 of sorted "node_id:exception_type" pairs. An identical
  signature on consecutive attempts means the last edit changed nothing — escalate to
  EXHAUSTED instead of burning attempt 3 on the same hypothesis.
- MAX_FIX_ATTEMPTS comes from settings, never typed inline.
- Run the FULL suite once before SUMMARIZING — green on three tests is not green.
- Add the guard that flags a diff touching only test files. That is the most common way
  an autonomous agent produces a green, worthless PR.
- No TestOutputParser ABC yet (Claude.md section 9) — one implementation.

The integration test is the epic's proof: a fixture repo with a deliberate bug and a
scripted provider that fixes it on attempt 2, asserting the state path
TESTING → EDITING → TESTING → SUMMARIZING.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E9 — Human Approval Gate & Safety

```
Implement Epic E9 (Human Approval Gate & Safety) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-prompt-authoring for the change-summary prompt, and
devmind-testing for the tests.

Spec:   docs/specs/epic-09-approval-gate-safety.md
Tasks:  docs/02-epic-breakdown.md, section E9
Design: docs/01-solution-design.md sections 3 and 9

E1-E8 are complete — read them first.

Treat this epic as security work, not feature work. It is the guarantee the whole
project rests on.

Build ChangeSummaryService, DiffService, the ApprovalRequest payload, ApprovalService,
RemoteOperationGuard, the complete tests/safety/ suite, and docs/SAFETY.md.

From the spec:
- decided_by is REQUIRED. An approval with no named human is not an approval.
- Rejection requires a reason; the workspace is retained; nothing is retried.
- NO timeout and NO auto-approve, ever. AWAITING_APPROVAL is durable and waits forever.
  Include the grep test that fails if auto_approve or approval_timeout ever appears in
  the source.
- The approval token is single-use and session-bound.
- The warnings list must surface UNVERIFIED, tests-only-diff, cost-ceiling-hit, and
  subprocess-sandbox. A human skimming must be unable to miss them.
- The change_summary prompt must REQUIRE risk notes — what the agent was unsure about
  is the most valuable thing it knows.

Write one named test per invariant SI-1 through SI-8, plus the structural test that
PR_OPENED is reachable only from APPROVED. Add tests/safety/README.md stating that a
failing safety test is never fixed by editing the test.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E10 — GitHub Integration & PR Delivery

```
Implement Epic E10 (GitHub Integration & PR Delivery) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-git-flow for branch and commit conventions,
devmind-prompt-authoring for the PR body prompt, devmind-testing for the tests.

Spec:   docs/specs/epic-10-github-pr-delivery.md
Tasks:  docs/02-epic-breakdown.md, section E10
Design: docs/01-solution-design.md sections 3 (SI-3, SI-6) and 10

E1-E9 are complete. Before writing any code, run `pytest tests/safety -v` and confirm
it is green. The gate must exist before the thing it gates.

Build GitService, BranchNamer, PRService, the pr_body prompt, dry-run mode, and the
failure paths.

From the spec:
- RemoteOperationGuard.authorize() is the FIRST statement in open_draft_pr(). Not after
  a log line, not after a validation. The test asserts an unapproved session produces
  ZERO git invocations, which only holds if nothing runs before the guard.
- Always --draft. No gh pr merge, no --auto, no --force, no branch deletion, anywhere.
  Include the grep tests that prove it.
- The commit carries an Approved-by trailer naming the human, and the PR body carries a
  provenance footer. A reviewer must never have to guess whether a human looked at this.
- Every failure keeps the work and hands the human a next step. Nothing is ever retried
  against a remote automatically. If you find yourself writing a retry-the-push helper,
  stop.
- All tests use a FakeGitHub / mocked CommandRunner that records argv and executes
  nothing. No test touches a real remote.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E11 — API, Streaming & Operator UX

```
Implement Epic E11 (API, Streaming & Operator UX) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-testing for the tests.

Spec:   docs/specs/epic-11-api-streaming-operator-ux.md
Tasks:  docs/02-epic-breakdown.md, section E11
Design: docs/01-solution-design.md sections 12 and 15

E1-E10 are complete — read them first.

Build the Container wiring class, the session/approval/event routers, the RFC-7807 error
handler mapping, the SSE stream service, and the rich-based CLI client.

From the spec:
- Routers stay thin: no ORM model imported in api/, no HTTPException raised in a
  service. If a router grows a conditional over domain state, that logic is a service's.
- SSE must be resumable via Last-Event-ID, with a 15s heartbeat, terminating on a
  terminal status and leaking no task on disconnect.
- Polling the event table at 0.5s is the right implementation. Do not add pub/sub.
- Never expose the approval token over the API.
- CLI approve requires typing the session id to confirm — not a y/n keypress. Approving
  an autonomous agent's code change should take a deliberate second.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## E12 — Quality, Hardening & Delivery

```
Implement Epic E12 (Quality, Hardening & Delivery) for DevMind.

Use the devmind-epic-implementation skill as your workflow, devmind-standards for
coding decisions, devmind-testing for the test strategy.

Spec:   docs/specs/epic-12-quality-hardening-delivery.md
Tasks:  docs/02-epic-breakdown.md, section E12
Design: docs/01-solution-design.md section 19

E1-E11 are complete — read them first.

Build the end-to-end golden test, the coverage gate, the property tests, the hardening
work, and all the delivery artifacts.

The e2e golden test is the most valuable test in the repository — write it first. A
fixture repo with a seeded bug, a scripted FakeLLMProvider that patches wrongly, reads
the failure, and patches correctly, asserting the exact state path through one real
self-correction, stopping at AWAITING_APPROVAL, then approving and opening a draft PR
with a mocked gh. Real sandbox, real database, real state machine, real tools, real
parsers — only the LLM and gh are faked.

Write the rejection variant too: reject → REJECTED, reason persisted, zero git
operations, workspace retained. The claim is "it stops when a human says no", and an
untested claim is a marketing line.

If the e2e test is hard to write, that is information about the design. Take it
seriously rather than working around it with mocks.

Then: coverage gate at 85% on services/tools/repositories, property tests for the state
machine and path guard, graceful shutdown, restart recovery, SecretRedactor, workspace
retention, Dockerfile, docker-compose, GitHub Actions CI with the safety job SEPARATE
so its failure is unmissable, docs/DEMO.md including the rejection path, and the five
ADRs.

The README is the front door. It must include the honest-limitations section: Python
and pytest only, subprocess sandbox is not a security boundary, scoped to small
well-specified issues, no vector index, single process. A README that oversells is
worse than no README.

Add no new features in this epic. It is about proving what exists.

When make check is green, invoke test-runner, then standards-auditor. Fix everything
and re-run make check.

Report in the devmind-epic-implementation format. Do not commit.
```

---

## Delivery — after each epic

Run this **only when you have read the epic's report and are satisfied.** The `git-pr`
subagent will not act without an explicit instruction, and this is that instruction.

```
Epic E<n> is complete and I have reviewed the report. Commit it.

Invoke the git-pr subagent. I am explicitly authorising: create the branch, stage, and
commit. Do NOT push and do NOT open a PR yet.

Branch: epic/e<nn>-<slug>
Use the devmind-git-flow skill for the branch name and commit message format.
Run make check first and do not commit over a red suite.
```

## Delivery — push and open the draft PR

```
Push epic E<n> and open a draft PR.

Invoke the git-pr subagent. I am explicitly authorising: push the branch and open a
DRAFT pull request. Not a merge — draft only.

Use the devmind-git-flow skill's PR body template. Include the real make check output
in the Testing section and the epic/spec references in the Scope section.
```

## Full milestone review before delivery

Use this at a milestone boundary (M1 after E2, M2 after E6, M3 after E8, M4 after E10,
M5 after E12), before pushing anything:

```
Review milestone M<n> before I decide on delivery.

1. Invoke the test-runner subagent over the whole repository — full suite, lint, types,
   coverage, and the safety suite reported separately.
2. Invoke the standards-auditor subagent over all of src/devmind — I want both
   violations of Claude.md and over-application of it (unjustified ABCs, premature
   infrastructure).
3. Give me a consolidated verdict: is this milestone's acceptance criteria met, per
   docs/02-epic-breakdown.md?

Do not commit, push, or open a PR. I will decide after reading the verdict.
```

---

## Rules that hold across every prompt

- **Never skip the two review subagents.** They are the quality gate, and they are cheap
  compared to finding the same problems three epics later.
- **Never move on over a red `make check`.** Debt compounds fastest in a layered build.
- **Never let an epic commit itself.** Delivery is always a separate, explicit instruction.
- **A failing test in `tests/safety/` is never fixed by editing the test.** Fix the code, or
  bring it to a human.
- **Read the Deviations section of every report.** A spec that turned out wrong is worth
  knowing about before four more epics are built on it.
