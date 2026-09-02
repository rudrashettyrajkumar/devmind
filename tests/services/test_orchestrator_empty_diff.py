"""`SessionOrchestrator` — an editing phase that changes no file fails the session
(E7-F3-T4, acceptance criteria)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, SessionStatus
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.fakes.fake_workbench_builder import FakeRepoIngestionService, make_ingestion_result
from tests.services._agent_kit import build_orchestrator

_PLAN = [
    {"content": "Inspect calc.py add() for the wrong operator", "status": "pending"},
    {"content": "Correct the operator and re-run the suite", "status": "pending"},
]


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="wrong result")
    ).id


async def test_empty_diff_after_editing_fails_the_session(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    sandbox = FakeSandbox()  # default `git diff` -> empty stdout
    ingestion = FakeRepoIngestionService(result=make_ingestion_result(sid, tool_workspace))
    planner_llm = FakeLLMProvider([tool_call("todo_write", items=_PLAN)])
    loop_llm = FakeLLMProvider(
        [
            tool_call("finish", summary="Found it in calc.py", confidence=0.8),
            tool_call("finish", summary="I believe I fixed it", confidence=0.9),
        ]
    )
    orchestrator, _ = build_orchestrator(
        db_session,
        ingestion=ingestion,
        loop_llm=loop_llm,
        planner_llm=planner_llm,
        sandbox=sandbox,
    )

    await orchestrator.run(sid)

    model = session_repo.get_by_id(sid)
    assert model.status is SessionStatus.FAILED
    assert model.failure_reason is not None
    assert "no working-tree change" in model.failure_reason

    kinds = [e.event_type for e in EventRepository(db_session).list_since(sid)]
    assert EventType.SESSION_FAILED in kinds
    assert sandbox.teardown_calls == 1  # cleanup still ran
