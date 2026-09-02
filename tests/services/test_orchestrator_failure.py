"""`SessionOrchestrator` — an ingestion error ends the session FAILED with a reason,
and the run unwinds cleanly (E7-F3, acceptance criteria)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, SessionStatus
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.fakes.fake_workbench_builder import FakeRepoIngestionService
from tests.services._agent_kit import build_orchestrator


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/x/y", issue_number=42)).id


async def test_ingestion_failure_fails_the_session(
    db_session: SQLAlchemySession, session_repo: SessionRepository, sid: str
) -> None:
    ingestion = FakeRepoIngestionService(raises="issue #42 could not be fetched: gh exited 1")
    planner_llm = FakeLLMProvider([tool_call("todo_write", items=[{"content": "unused"}])])
    loop_llm = FakeLLMProvider([tool_call("finish", summary="unused", confidence=0.5)])
    orchestrator, workbench_builder = build_orchestrator(
        db_session,
        ingestion=ingestion,
        loop_llm=loop_llm,
        planner_llm=planner_llm,
        sandbox=FakeSandbox(),
    )

    await orchestrator.run(sid)

    model = session_repo.get_by_id(sid)
    assert model.status is SessionStatus.FAILED
    assert model.failure_reason is not None
    assert "could not be fetched" in model.failure_reason

    kinds = [e.event_type for e in EventRepository(db_session).list_since(sid)]
    assert EventType.SESSION_FAILED in kinds
    assert workbench_builder.built == []  # never got past ingestion
    assert ingestion.calls == [sid]
