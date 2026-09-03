"""`ChangeSummaryService` — risk notes and issue understanding are required (E9-F1-T1).

Proves the two payload-bound sections are parsed out of the model's markdown, that a
summary omitting either is rejected as unusable, and that the prompt is rendered over
the real diff / plan / evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.exceptions import LLMProviderError
from devmind.prompts.loader import PromptLoader
from devmind.repositories import SessionRepository
from devmind.schemas.session import SessionCreate, SessionRead
from devmind.services.change_summary_service import ChangeSummaryService
from devmind.services.diff_service import DiffService
from devmind.services.workspace_path_guard import WorkspacePathGuard
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text
from tests.fakes.fake_sandbox import FakeSandbox, command_result

_GOOD_SUMMARY = """\
### Issue understanding

The reporter wants naive datetimes to be treated as UTC in parse_timestamp.

### Summary

parse_timestamp raised on naive input. It now assumes UTC.

### Changes by file

- src/pkg/parser.py — coerce naive datetimes to UTC before comparison.

### Verification

baseline 128 passed / 1 pre-existing failure; final 129 passed / 0 failed.

### Risks and uncertainties

- The UTC assumption is wrong for callers that meant local time.
- No test covers a timezone-aware input with a non-UTC offset.
"""

_NO_UNDERSTANDING = _GOOD_SUMMARY.replace(
    "### Issue understanding\n\n"
    "The reporter wants naive datetimes to be treated as UTC in parse_timestamp.\n\n",
    "",
)

_EMPTY_RISKS = _GOOD_SUMMARY.split("### Risks and uncertainties")[0] + (
    "### Risks and uncertainties\n\n"
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def session(db_session: SQLAlchemySession, workspace: Path) -> SessionRead:
    repo = SessionRepository(db_session)
    model = repo.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=42))
    repo.record_ingestion(
        model.id,
        base_commit_sha="abc123",
        default_branch="main",
        workspace_path=str(workspace),
        has_test_suite=True,
        issue_title="parse_timestamp rejects naive datetimes",
    )
    return SessionRead.model_validate(repo.get_by_id(model.id))


def _service(llm: FakeLLMProvider, workspace: Path) -> ChangeSummaryService:
    sandbox = FakeSandbox(default=command_result(stdout="diff --git a/p b/p\n+utc\n"))
    diffs = DiffService(sandbox, WorkspacePathGuard(workspace))
    return ChangeSummaryService(llm, PromptLoader(), diffs)


async def test_parses_understanding_and_risk_notes(session: SessionRead, workspace: Path) -> None:
    llm = FakeLLMProvider([final_text(_GOOD_SUMMARY)])
    summary = await _service(llm, workspace).summarize(
        session, plan_text="1. fix it", test_evidence_text="baseline vs final"
    )

    assert "naive datetimes" in summary.issue_understanding
    assert len(summary.risk_notes) == 2
    assert summary.risk_notes[0].startswith("The UTC assumption is wrong")
    assert summary.markdown.startswith("### Issue understanding")


async def test_prompt_is_rendered_over_diff_plan_and_evidence(
    session: SessionRead, workspace: Path
) -> None:
    llm = FakeLLMProvider([final_text(_GOOD_SUMMARY)])
    await _service(llm, workspace).summarize(
        session, plan_text="1. coerce to UTC", test_evidence_text="129 passed"
    )

    sent = llm.last_request().messages[0]["content"][0]["text"]  # type: ignore[index]
    assert "1. coerce to UTC" in sent
    assert "129 passed" in sent
    assert "+utc" in sent


async def test_missing_issue_understanding_is_unusable(
    session: SessionRead, workspace: Path
) -> None:
    llm = FakeLLMProvider([final_text(_NO_UNDERSTANDING)])
    with pytest.raises(LLMProviderError):
        await _service(llm, workspace).summarize(
            session, plan_text="1. fix", test_evidence_text="ok"
        )


async def test_empty_risk_section_is_unusable(session: SessionRead, workspace: Path) -> None:
    llm = FakeLLMProvider([final_text(_EMPTY_RISKS)])
    with pytest.raises(LLMProviderError):
        await _service(llm, workspace).summarize(
            session, plan_text="1. fix", test_evidence_text="ok"
        )
