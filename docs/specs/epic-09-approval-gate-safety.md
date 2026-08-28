# Spec — E9: Human Approval Gate & Safety

| | |
|---|---|
| **Epic** | E9 |
| **Depends on** | E2, E7, E8 |
| **Blocks** | E10 |
| **Size** | L (~2 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

The guarantee the entire project rests on: **nothing leaves the machine without a human saying
so.** This epic builds the review payload a human actually needs, the gate itself, and the test
suite that proves every safety invariant holds.

Read this spec as security work, not feature work.

## Design references

`docs/01-solution-design.md` §3 (SI-1…SI-8), §9 (approval gate).

## Contracts

### The review payload

A human deciding in ninety seconds needs evidence, not prose.

```python
class ApprovalRequest(BaseModel):
    session_id: str
    repo_url: str
    issue: IssueRead
    issue_understanding: str            # the agent's restatement of the problem
    plan: list[TodoItemRead]
    summary: ChangeSummary
    diff: str
    diff_stats: list[FileDiffStat]      # path, added, removed
    test_evidence: TestEvidence
    risk_notes: list[str]
    warnings: list[str]                 # UNVERIFIED, tests-only diff, budget notes
    metrics: SessionMetrics             # attempts, steps, wall time, tokens, cost_usd
    created_at: datetime
```

```python
class TestEvidence(BaseModel):
    baseline: TestRunSummary | None
    final: TestRunSummary | None
    attempts: list[TestRunSummary]
    pre_existing_failures: list[str]
    unverified: bool = False
```

`warnings` is the load-bearing field. It must include, when true:
`"UNVERIFIED — no test suite found in this repository"`,
`"The diff modifies only test files"`,
`"Session hit its cost ceiling"`,
`"Sandbox backend was `subprocess` — process isolation only, not a security boundary"`.

A human skimming should be unable to miss any of these.

### `ChangeSummaryService`

```python
class ChangeSummaryService:
    def __init__(self, llm: LLMProvider, prompts: PromptLoader, diffs: DiffService) -> None: ...
    async def summarize(self, session: SessionModel) -> ChangeSummary: ...
```

Renders `change_summary.md` over the final diff, the plan, and the test evidence. The prompt
requires **risk notes** — the agent must state what it was unsure about, what it did not verify,
and what a reviewer should look at hardest. An agent that reports only confidence has not been
useful; the uncertainty is the most valuable thing it knows.

### `DiffService`

```python
class DiffService:
    def __init__(self, sandbox: Sandbox, guard: WorkspacePathGuard) -> None: ...
    async def unified_diff(self, workspace: Path) -> str: ...
    async def file_stats(self, workspace: Path) -> list[FileDiffStat]: ...
    async def touches_only_tests(self, workspace: Path, profile: RepoProfile) -> bool: ...
```

`git diff` against the base commit, capped at `MAX_DIFF_CHARS` with an explicit truncation
marker — a truncated diff must never be presented as complete.

### `ApprovalService` — the gate

```python
class ApprovalService:
    def __init__(self, approvals: ApprovalRepository, sessions: SessionRepository,
                 state: SessionStateMachine, events: EventRepository) -> None: ...

    async def request(self, session_id: str) -> ApprovalRecord:
        """SUMMARIZING → AWAITING_APPROVAL. Creates a single-use token."""

    async def decide(self, session_id: str, decision: ApprovalDecision,
                     *, decided_by: str, reason: str | None = None) -> ApprovalRecord:
        """AWAITING_APPROVAL → APPROVED | REJECTED."""

    async def assert_approved(self, session_id: str) -> ApprovalRecord:
        """Raises ApprovalRequiredError / ApprovalAlreadyConsumedError. Called by PRService."""

    async def consume(self, session_id: str) -> None:
        """Marks the approval used. Called once, after the PR is opened."""
```

Rules, each with a test:

- `request()` from any state other than `SUMMARIZING` raises `InvalidStateTransitionError`.
- `decide()` on a session not in `AWAITING_APPROVAL` raises.
- `decide()` twice raises — a decision is final.
- `decided_by` is **required**. An approval with no named human is not an approval.
- Rejection requires a reason.
- **No timeout, no auto-approve, ever.** `AWAITING_APPROVAL` is durable and waits forever. A
  timeout that defaults to "approve" would silently void the entire safety model; a timeout that
  defaults to "reject" is a feature nobody asked for. Neither exists.

### `RemoteOperationGuard`

```python
class RemoteOperationGuard:
    def __init__(self, approvals: ApprovalService, settings: Settings) -> None: ...

    async def authorize(self, session_id: str, operation: str) -> ApprovalRecord:
        """The only door to a remote operation. Raises unless APPROVED and unconsumed."""
```

Every remote-capable call in E10 goes through this first. It re-reads the record from the
database rather than trusting anything the caller passes — safety layer 3 (design §9).

### The rejection path

`decide(REJECTED)` → status `REJECTED`, reason persisted, `APPROVAL_DECIDED` event, workspace
**retained** for inspection, `completed_at` set. No retry, no "are you sure", no fallback. A
human said no; the system's job is to stop cleanly and leave the evidence intact.

## The safety test suite — `tests/safety/`

The most important directory in the repository. One named test per invariant:

```python
async def test_si1_no_tool_can_reach_a_remote(registry): ...
async def test_si2_sandbox_environment_carries_no_credentials(sandbox): ...
async def test_si3_pr_service_refuses_without_approval(pr_service, unapproved_session, fake_gh):
    with pytest.raises(ApprovalRequiredError):
        await pr_service.open_draft_pr(unapproved_session.id)
    assert fake_gh.invocations == []          # and did nothing on the way out

async def test_si4_approval_token_is_single_use(approval_service, approved_session): ...
async def test_si5_every_path_taking_tool_rejects_escapes(executor, tool_context): ...
async def test_si6_pr_is_always_draft_and_no_merge_call_exists():
    src = subprocess.run(["grep", "-rn", "pr merge", "src/"], capture_output=True, text=True)
    assert src.stdout == ""

async def test_si7_every_state_transition_emits_an_event(state_machine, event_repo): ...
async def test_si8_disallowed_binary_is_rejected_before_execution(sandbox): ...
```

Plus the structural ones:

```python
def test_pr_opened_is_reachable_only_from_approved():
    sources = [s for s in SessionStatus
               if SessionStatus.PR_OPENED in _LEGAL_TRANSITIONS[s]]
    assert sources == [SessionStatus.APPROVED]

def test_no_approval_timeout_exists():
    """Guards against a future 'convenience' auto-approve."""
    src = Path("src/devmind").rglob("*.py")
    for f in src:
        text = f.read_text()
        assert "auto_approve" not in text
        assert "approval_timeout" not in text
```

**A failing safety test is never fixed by editing the test.** Fix the code, or bring it to a
human. Write that sentence into `tests/safety/README.md`.

### `docs/SAFETY.md`

One page: each invariant, the mechanism enforcing it, and the named test proving it. This is
what someone evaluating the project reads first, and it is the artifact that turns a claim into
evidence.

## Task plan

E9-F1-T1 … E9-F3-T5. Payload → gate → guard → safety suite → SAFETY.md.

## Testing

Beyond the safety suite:

| Test | Proves |
|---|---|
| `test_approval_service.py` | Request/decide happy paths; every illegal call raises; `decided_by` required; double-decide rejected |
| `test_approval_request_payload.py` | Every field populated; warnings appear when their conditions hold |
| `test_change_summary_service.py` | Risk notes required and populated; prompt variables validated |
| `test_diff_service.py` | Unified diff correct; stats correct; truncation marked; tests-only detection |
| `test_rejection_path.py` | `REJECTED` persisted with reason; workspace retained; nothing pushed |
| `test_durable_wait.py` | An `AWAITING_APPROVAL` session survives a simulated restart and is still decidable |

## Acceptance criteria

- [ ] Every invariant SI-1…SI-8 has a named test that fails if the invariant breaks.
- [ ] `PRService` refuses an unapproved session **and performs zero git operations** on the way out.
- [ ] A replayed approval token raises `ApprovalAlreadyConsumedError`.
- [ ] `PR_OPENED` is reachable only from `APPROVED`; asserted structurally.
- [ ] No auto-approve or approval-timeout code exists; asserted by grep test.
- [ ] The approval payload surfaces `UNVERIFIED` and tests-only-diff warnings.
- [ ] `docs/SAFETY.md` maps every invariant to its test.
- [ ] `make check` green.

## Notes

- Layer the enforcement, and keep all three: capability separation (the tool doesn't exist),
  state machine (the transition is illegal), guard clause (the record is re-read). Any one of
  them can be defeated by a future refactor; all three failing silently at once is unlikely.
- Resist adding an "approve all future sessions for this repo" convenience. It voids the model
  in exchange for saving a click.
- The `decided_by` string ends up in the PR body and the commit trailer. A human's name is
  attached to what gets opened — that is the point, and it is also why it cannot be optional.
