"""`AgentLoop` — one scripted tool call runs, its result is appended, END_TURN exits
(E7-F1-T2)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase, EventType
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.services._agent_kit import full_registry, make_context, make_loop, make_tool_context


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="add is wrong")
    ).id


async def test_scripted_tool_call_then_end_turn(
    db_session: SQLAlchemySession, tool_workspace, sid: str
) -> None:
    llm = FakeLLMProvider([tool_call("list_dir", path="."), final_text("all done")])
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.INVESTIGATION)
    loop = make_loop(llm, db_session, registry)

    outcome = await loop.run(ctx, tctx, AgentPhase.INVESTIGATION)

    assert outcome.status.value == "completed"
    assert outcome.final_text == "all done"
    assert outcome.steps_used == 1
    assert llm.call_count == 2

    tool_results = [
        block
        for message in ctx.messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1

    kinds = [e.event_type for e in EventRepository(db_session).list_since(sid)]
    assert EventType.LLM_CALL in kinds
    assert EventType.TOOL_CALL in kinds
