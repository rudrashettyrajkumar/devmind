"""Shared harness for the `PRService` tests (E10-F2).

Builds a real `PRService` over in-memory repositories and the real approval gate,
faking only what would touch the network: the `CommandRunner` behind `GitService` /
`GitHubClient` (records argv, executes nothing) and the two `LLMProvider`s behind the
change summary and the PR body.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.config import Settings
from devmind.core.enums import ApprovalDecision, SessionStatus
from devmind.prompts.loader import PromptLoader
from devmind.repositories import (
    ApprovalRepository,
    EventRepository,
    PullRequestRepository,
    SessionRepository,
    TestRunRepository,
    TodoRepository,
)
from devmind.schemas.session import SessionCreate
from devmind.services.approval_request_builder import ApprovalRequestBuilder
from devmind.services.approval_service import ApprovalService
from devmind.services.branch_namer import BranchNamer
from devmind.services.change_summary_service import ChangeSummaryService
from devmind.services.diff_service import DiffService
from devmind.services.git_service import GitService
from devmind.services.github_client import GitHubClient
from devmind.services.pr_body_composer import PrBodyComposer
from devmind.services.pr_service import PRService
from devmind.services.remote_operation_guard import RemoteOperationGuard
from devmind.services.session_state_machine import SessionStateMachine
from devmind.services.workspace_path_guard import WorkspacePathGuard
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text
from tests.fakes.fake_sandbox import FakeSandbox, command_result

PR_URL = "https://github.com/acme/widget/pull/7"
HEAD_SHA = "abcdef0123456789abcdef0123456789abcdef01"

_SUMMARY_MD = """\
### Issue understanding

parse_timestamp rejected naive datetimes; the reporter needs it to assume UTC.

### Summary

Naive datetimes are now coerced to UTC before formatting.

### Changes by file

- src/pkg/parser.py — coerce naive datetimes to UTC.

### Verification

final: 12 passed, 0 failed.

### Risks and uncertainties

- The UTC assumption may be wrong for local-time callers.
"""

_PR_BODY_MD = """\
## Summary

Coerce naive datetimes to UTC in parse_timestamp.

## The issue

parse_timestamp raised on naive input.

Closes #42

## Changes

- src/pkg/parser.py — assume UTC for naive datetimes.

## Test evidence

```
baseline: 12 passed, 0 failed
final:    12 passed, 0 failed
```

The suite is green.

## Risks and what to review closely

- Confirm UTC is the right assumption for this codebase.
"""

_DIFF = "diff --git a/src/pkg/parser.py b/src/pkg/parser.py\n+utc coerce\n"
_NUMSTAT = "5\t2\tsrc/pkg/parser.py\n"


class CapturingRunner(FakeCommandRunner):
    """The default kit runner: records every `--body-file` payload before the temp
    file is unlinked, so a test can assert on the PR body `gh` was handed.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.pr_bodies: list[str] = []

    async def run(self, argv, **kwargs):  # type: ignore[no-untyped-def, override]
        args = list(argv)
        if "--body-file" in args:
            path = args[args.index("--body-file") + 1]
            self.pr_bodies.append(Path(path).read_text(encoding="utf-8"))
        return await super().run(args, **kwargs)


_TO_SUMMARIZING = (
    SessionStatus.INGESTING,
    SessionStatus.PLANNING,
    SessionStatus.INVESTIGATING,
    SessionStatus.EDITING,
    SessionStatus.TESTING,
    SessionStatus.SUMMARIZING,
)


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"anthropic_api_key": "sk-ant-test"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@dataclass
class PrHarness:
    service: PRService
    runner: FakeCommandRunner
    body_llm: FakeLLMProvider
    summary_llm: FakeLLMProvider
    session_id: str
    sessions: SessionRepository
    prs: PullRequestRepository
    approvals: ApprovalRepository
    events: EventRepository


async def build_harness(
    db_session: SQLAlchemySession,
    workspace: Path,
    *,
    approve: bool = True,
    runner: FakeCommandRunner | None = None,
    dry_run: bool = False,
    issue_number: int | None = 42,
) -> PrHarness:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    todos = TodoRepository(db_session)
    runs = TestRunRepository(db_session)
    approvals_repo = ApprovalRepository(db_session)
    prs = PullRequestRepository(db_session)
    machine = SessionStateMachine(sessions, events)
    approval_service = ApprovalService(approvals_repo, sessions, machine, events)

    model = sessions.create(
        SessionCreate(
            repo_url="https://github.com/acme/widget",
            issue_number=issue_number,
            issue_description=None if issue_number else "parse_timestamp rejects naive datetimes",
        )
    )
    session_id = model.id
    sessions.record_ingestion(
        session_id,
        base_commit_sha="base000",
        default_branch="main",
        workspace_path=str(workspace),
        has_test_suite=True,
        issue_title="parse_timestamp rejects naive datetimes" if issue_number else None,
        issue_body="It should assume UTC.",
    )
    for step in _TO_SUMMARIZING:
        machine.transition(session_id, step)
    todos.replace_all(session_id, ["Coerce naive datetimes to UTC"])
    for attempt, is_baseline in ((0, True), (1, False)):
        runs.create(
            session_id,
            attempt=attempt,
            is_baseline=is_baseline,
            exit_code=0,
            passed=12,
            failed=0,
            errors=0,
            signature=None if is_baseline else "sig",
            report={},
            duration_seconds=1.0,
        )

    await approval_service.request(session_id)
    if approve:
        await approval_service.decide(
            session_id, ApprovalDecision.APPROVED, decided_by="Dana Reviewer"
        )

    guard = RemoteOperationGuard(approval_service)

    ws_guard = WorkspacePathGuard(workspace)
    sandbox = FakeSandbox(
        [
            command_result(stdout=_DIFF),
            command_result(stdout=_DIFF),
            command_result(stdout=_NUMSTAT),
            command_result(stdout=_NUMSTAT),
        ]
    )
    diffs = DiffService(sandbox, ws_guard)
    summary_llm = FakeLLMProvider([final_text(_SUMMARY_MD)])
    review_builder = ApprovalRequestBuilder(
        sessions,
        todos,
        runs,
        ChangeSummaryService(summary_llm, PromptLoader(), diffs),
        diffs,
        max_session_cost_usd=5.0,
    )

    if runner is None:
        runner = CapturingRunner(
            by_prefix={
                ("git", "rev-parse"): command_output(["git"], stdout=f"{HEAD_SHA}\n"),
                ("git",): command_output(["git"]),
                ("gh", "pr", "create"): command_output(["gh"], stdout=f"{PR_URL}\n"),
            }
        )
    body_llm = FakeLLMProvider([final_text(_PR_BODY_MD)])

    service = PRService(
        guard,
        review_builder,
        GitService(runner, ws_guard, settings(dry_run=dry_run)),
        GitHubClient(runner, token=None),
        PrBodyComposer(body_llm, PromptLoader()),
        BranchNamer(),
        prs,
        sessions,
        events,
        machine,
        approval_service,
        settings(dry_run=dry_run),
    )
    return PrHarness(
        service=service,
        runner=runner,
        body_llm=body_llm,
        summary_llm=summary_llm,
        session_id=session_id,
        sessions=sessions,
        prs=prs,
        approvals=approvals_repo,
        events=events,
    )
