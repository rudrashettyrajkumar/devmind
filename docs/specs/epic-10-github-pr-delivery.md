# Spec — E10: GitHub Integration & PR Delivery

| | |
|---|---|
| **Epic** | E10 |
| **Depends on** | E9 |
| **Blocks** | E11 |
| **Size** | M (~1.5 days) |
| **Skills** | `devmind-standards`, `devmind-git-flow`, `devmind-testing` |

## Purpose

The only epic in the project permitted to touch a remote — and only through the door E9 built.
Branch, commit, push, open a **draft** PR. Nothing else, ever.

> **Do not start this epic until E9's safety suite is green.** The gate must exist before the
> thing it gates.

## Design references

`docs/01-solution-design.md` §3 (SI-3, SI-6), §10 (GitHub integration).

## Contracts

### `GitService`

```python
class GitService:
    def __init__(self, runner: CommandRunner, guard: WorkspacePathGuard,
                 settings: Settings) -> None: ...

    async def create_branch(self, workspace: Path, name: str) -> str: ...
    async def stage_all(self, workspace: Path) -> None: ...
    async def commit(self, workspace: Path, message: CommitMessage) -> str: ...   # returns sha
    async def push(self, workspace: Path, branch: str) -> None: ...               # GATED
```

**`push()` is the first remote-capable method in the codebase.** It takes an already-validated
`ApprovalRecord` or is called only from `PRService` after `RemoteOperationGuard.authorize()`.
Never `--force`, never to a default branch, never a branch delete.

Branch naming (`devmind-git-flow`):

```python
class BranchNamer:
    def build(self, issue_number: int | None, title: str) -> str:
        # devmind/issue-42-fix-timezone-parsing
        # collision → devmind/issue-42-fix-timezone-parsing-2
```

Slug: lowercase, ASCII, hyphenated, ≤ 40 chars, no trailing hyphen.

Commit message:

```
fix(parser): handle naive datetimes in parse_timestamp

<the agent's change summary, wrapped at 72>

Refs: #42
Session: 3f9a-...
Approved-by: <decided_by>
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

The `Approved-by` trailer puts a human's name on the change permanently. That is the audit trail
doing its job.

### `PRService`

```python
class PRService:
    def __init__(self, git: GitService, github: GitHubClient, guard: RemoteOperationGuard,
                 prs: PullRequestRepository, state: SessionStateMachine,
                 prompts: PromptLoader, llm: LLMProvider, settings: Settings) -> None: ...

    async def open_draft_pr(self, session_id: str) -> PullRequestRead:
        approval = await self._guard.authorize(session_id, "open_draft_pr")   # ← LINE ONE
        ...
```

**The guard call is the first statement in the method.** Not after a validation, not after a log
line — first. The test asserts that an unapproved session produces zero git invocations, which
only holds if nothing runs before the guard.

Then, in order:

1. Create the branch.
2. Stage and commit.
3. `push` (gated).
4. Render `pr_body.md`.
5. `gh pr create --draft --base <default_branch> --head <branch> --title ... --body-file ...`
6. Persist `PullRequestModel`, emit `PR_OPENED`, transition `APPROVED → PR_OPENED`.
7. `approvals.consume(session_id)` — the token is now spent.

### PR body

Rendered from `pr_body.md`. Mandatory sections:

```markdown
## Summary
## The issue
Closes #42
## Changes
## Test evidence
  baseline: 128 passed, 1 failed (pre-existing)
  final:    129 passed, 0 failed
  fix attempts used: 2 of 3
## Risks and what to review closely
## Provenance
Produced autonomously by DevMind (session `3f9a…`), reviewed and approved by
<decided_by> on <timestamp>. Sandbox: docker. Model: claude-opus-5.
Cost: $0.83. This PR is a draft and has not been merged.
```

The provenance footer is not optional. A reviewer must never have to guess whether a human
looked at this before it appeared.

### Failure handling

| Failure | Behaviour |
|---|---|
| Push rejected (non-fast-forward) | `FAILED`, branch retained locally, **no force-push, no retry** |
| No push permission | `FAILED` with an actionable message about the token's scopes |
| Branch already exists on remote | `FAILED` — never overwrite someone else's branch |
| `gh pr create` fails | `FAILED`; the branch is pushed, so record that clearly for the human |
| `gh` unauthenticated | Caught at `/health` and at session start, long before this point |

Every failure keeps the work and hands the human a clear next step. Nothing is retried against a
remote automatically.

### Dry-run mode

`settings.dry_run` → log the exact argv that *would* run, execute nothing remote, return a
synthetic `PullRequestRead`. This makes the whole delivery path demonstrable without a real
repository, which matters for both the demo and the e2e test.

## Task plan

E10-F1-T1 … E10-F3-T3. Git ops → PR service → body → failure handling → guarantees.

## Testing

Everything against a `FakeGitHub` / mocked `CommandRunner` that **records argv and executes
nothing**. No test in this repo touches a real remote.

| Test | Proves |
|---|---|
| `test_branch_namer.py` | Slugging, length cap, collision suffixing |
| `test_git_service.py` | Exact argv for branch/stage/commit; message format including trailers |
| `test_pr_service_happy_path.py` | Full sequence, exact argv, `--draft` present, state → `PR_OPENED` |
| `test_pr_service_requires_approval.py` | **SI-3**: unapproved → raises, **zero** invocations recorded |
| `test_pr_service_consumes_token.py` | **SI-4**: second call raises `ApprovalAlreadyConsumedError` |
| `test_no_merge_anywhere.py` | **SI-6**: grep for `pr merge`, `--auto`, `--merge` across `src/` → empty |
| `test_no_force_push.py` | grep for `--force`, `-f` on push → empty |
| `test_pr_failure_paths.py` | Each failure → `FAILED` with the right reason; branch retained |
| `test_dry_run.py` | No remote argv executed; synthetic result returned |
| `test_pr_body.py` | All mandatory sections present, including the provenance footer |

## Acceptance criteria

- [ ] An approved session produces a draft PR; argv asserted exactly.
- [ ] An unapproved session cannot, and performs zero git operations.
- [ ] `--draft` is always present; no merge call exists anywhere in `src/`.
- [ ] No force-push, no branch deletion, no remote retry.
- [ ] The approval token is consumed exactly once.
- [ ] The PR body carries the provenance footer naming the approving human.
- [ ] Dry-run mode makes the full path demonstrable with no remote.
- [ ] `make check` green.

## Notes

- Use `gh` rather than an HTTP client: it already solves auth, and shelling to a CLI the user
  already trusts is more honest about the trust boundary than embedding a token in a request.
- `GitHubClient` stays a plain class — one implementation (`Claude.md` §9).
- If you find yourself writing a "retry the push" helper, stop. A failed push is a human's
  decision, not a loop's.
