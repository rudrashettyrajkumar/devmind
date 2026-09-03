# `tests/safety/` — the invariant suite

One named test per non-negotiable safety invariant (`docs/01-solution-design.md` §3,
SI-1…SI-8), plus the structural checks that hold the approval gate's shape.

## The one rule

**A failing safety test is never fixed by editing the test.**

A red test in this directory means the code broke an invariant the whole project
rests on. Fix the code, or bring it to a human. Do not weaken an assertion, loosen a
`pytest.raises`, or delete a case to get to green — that is not a fix, it is removing
the smoke detector because it went off.

## What each file covers

| File | Invariant |
|---|---|
| `test_si1_tool_registry.py` | SI-1 — the agent has no tool that reaches a remote |
| `test_si2_sandbox_isolation.py` | SI-2 — the sandbox carries no credentials; Docker has no network |
| `test_si3_approval_gate.py` | SI-3 — no remote op without a persisted `APPROVED` record; `PR_OPENED` reachable only from `APPROVED` |
| `test_si4_approval_single_use.py` | SI-4 — the approval token is single-use and session-bound |
| `test_si5_workspace_path_guard.py` / `test_si5_tool_path_escape.py` | SI-5 — every file write stays inside the workspace |
| `test_si6_no_merge.py` | SI-6 — no merge code path exists in `src/` |
| `test_si7_state_transition_events.py` | SI-7 — every state transition is persisted as an event |
| `test_si8_command_allowlist.py` | SI-8 — shell execution is bounded and allowlisted |
| `test_no_approval_timeout.py` | structural — no `auto_approve` / `approval_timeout` code exists |

See `docs/SAFETY.md` for the mechanism enforcing each invariant.
