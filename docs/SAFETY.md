# DevMind — Safety Model

DevMind runs an autonomous agent that edits real repositories. The guarantee the
whole project rests on is simple:

> **Nothing leaves the machine without a human saying so.**

That guarantee is not one check. It is a set of invariants, each enforced by a
specific mechanism, each proven by a named test that fails if the invariant breaks.
This page is the map. If you are evaluating DevMind, read this first.

## The non-negotiable invariants

| # | Invariant | Mechanism | Proven by |
|---|---|---|---|
| **SI-1** | The agent can never push, open a PR, merge, or contact a remote. | Capability separation. Push/PR code lives in `PRService` (E10), which is **not registered in the tool registry**. `ToolRegistry.build_tool_registry()` wires only read/edit/test tools. The agent's object graph contains no network-capable tool. | `tests/safety/test_si1_tool_registry.py` — asserts no registered tool name or source references a remote, and the registry set is exactly the intended eleven tools. |
| **SI-2** | Remote git operations are impossible from inside the agent's execution context. | The sandbox scrubs the environment to `SANDBOX_ENV_ALLOWLIST`, blanks every credential fragment, and forces `GIT_TERMINAL_PROMPT=0` / `GIT_ASKPASS=/bin/false`. `DockerSandbox` runs the session container with `network_mode="none"` — kernel-enforced. | `tests/safety/test_si2_sandbox_isolation.py` — the built environment blanks credentials; a real child process never sees a token; the Docker container is created with no network. |
| **SI-3** | `PRService.open_draft_pr()` refuses unless a persisted `ApprovalRecord` exists with `decision == APPROVED` and is unconsumed. | Three independent layers: (1) capability separation, as SI-1; (2) the state machine — `PR_OPENED` is reachable only from `APPROVED`, and `APPROVED` only from `AWAITING_APPROVAL` via `ApprovalService.decide()`; (3) `RemoteOperationGuard.authorize()` re-reads the record from the database at the point of use and is the first statement of every remote-capable method. | `tests/safety/test_si3_approval_gate.py` — the guard refuses a session that was never summarized, one still awaiting approval, and a rejected one; it allows only an approved, unconsumed one. Structural: `PR_OPENED` appears as a transition target from exactly `[APPROVED]`. E10 adds the "unapproved session performs zero git operations" test on `PRService` itself. |
| **SI-4** | Approval is single-use and session-bound. | `ApprovalModel` carries an opaque `secrets.token_urlsafe(32)` token, a session FK, and a `consumed_at` timestamp. `ApprovalService.consume()` sets it once; `assert_approved()` raises `ApprovalAlreadyConsumedError` on a spent token. | `tests/safety/test_si4_approval_single_use.py` — a second `authorize()` after `consume()` raises; a second `consume()` raises; the token is opaque and does not contain the session id. |
| **SI-5** | All file writes stay inside the session workspace. | `WorkspacePathGuard.resolve()` — reject absolute paths and any `..` component, reject any symlink among the traversed components, then `Path.resolve()` + `is_relative_to(workspace_root)`. Every path-taking tool routes its argument through it. | `tests/safety/test_si5_workspace_path_guard.py` (the named invariant checks) and `tests/safety/test_si5_tool_path_escape.py` (every path-taking tool rejects `../`, absolute, symlink-out, nested traversal). |
| **SI-6** | PRs are always opened as **drafts**, never merged. | `gh pr create --draft` (E10). No merge code path exists anywhere in `src/`. | `tests/safety/test_si6_no_merge.py` — grep for `pr merge`, `gh pr merge`, `--auto-merge`, `merge_pull_request` across `src/` returns nothing. |
| **SI-7** | Every state transition is persisted before it takes effect. | `SessionStateMachine.transition()` is the only code that changes a session's status, and it appends a `STATE_CHANGED` event in the same call. Sessions are replayable from the event log. | `tests/safety/test_si7_state_transition_events.py` — a full `CREATED → SUMMARIZING` walk plus the approval transitions each leave a `STATE_CHANGED` event with a `from` and a `to`. |
| **SI-8** | Shell execution is bounded and allowlisted. | `CommandAllowlist` rejects any binary outside `ALLOWED_COMMAND_BINARIES` before anything runs. Nothing uses `shell=True`. Every `SandboxCommand` carries a positive timeout (the schema makes zero/negative unconstructable) and output is truncated. | `tests/safety/test_si8_command_allowlist.py` — unlisted binaries raise before execution; no `shell=True` / `create_subprocess_shell` in `src/`; a non-positive timeout cannot be constructed. |

## Structural guarantees

- **No auto-approve, no approval timeout.** `AWAITING_APPROVAL` is durable and waits
  forever. `tests/safety/test_no_approval_timeout.py` greps `src/devmind` for
  `auto_approve` / `approval_timeout` and fails if either appears.
  `tests/services/test_durable_wait.py` proves an `AWAITING_APPROVAL` session
  survives a simulated restart and is still decidable.
- **`decided_by` is required.** `ApprovalService.decide()` rejects a blank deciding
  human. The name flows into the commit trailer and the PR body — a human's name is
  permanently attached to what gets opened.
- **Rejection is a first-class outcome.** `decide(REJECTED)` requires a reason,
  persists it, sets `completed_at`, emits `APPROVAL_DECIDED`, and **retains the
  workspace** for inspection. No retry, no fallback.
  (`tests/services/test_rejection_path.py`.)

## The layering principle

The approval gate keeps all three of its layers — capability separation, the state
machine, and the re-read guard clause — even though any one of them would stop an
unapproved PR today. Any single layer can be defeated by a future refactor. All three
failing silently at once is the scenario the redundancy exists for.
