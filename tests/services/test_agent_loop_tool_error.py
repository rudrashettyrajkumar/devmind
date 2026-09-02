"""`AgentLoop` — a failing tool yields an `is_error` result and the loop keeps going;
a tool outside the phase subset is refused structurally (E7-F1-T2, E7-F3-T3)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase, LoopStatus
from devmind.repositories import SessionRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.services._agent_kit import full_registry, make_context, make_loop, make_tool_context


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="bug")
    ).id


async def test_erroring_tool_does_not_stop_the_loop(
    db_session: SQLAlchemySession, tool_workspace, sid: str
) -> None:
    llm = FakeLLMProvider([tool_call("read_file", path="nope/missing.py"), final_text("moving on")])
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.INVESTIGATION)
    loop = make_loop(llm, db_session, registry)

    outcome = await loop.run(ctx, tctx, AgentPhase.INVESTIGATION)

    assert outcome.status is LoopStatus.COMPLETED
    assert llm.call_count == 2  # the loop went on to the second call
    error_blocks = [
        block
        for message in ctx.messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert error_blocks and error_blocks[0]["is_error"] is True


async def test_write_tool_is_refused_in_the_investigation_phase(
    db_session: SQLAlchemySession, tool_workspace, sid: str
) -> None:
    llm = FakeLLMProvider(
        [tool_call("write_file", path="hack.py", content="x = 1"), final_text("done")]
    )
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.INVESTIGATION)
    loop = make_loop(llm, db_session, registry)

    await loop.run(ctx, tctx, AgentPhase.INVESTIGATION)

    blocks = [
        block
        for message in ctx.messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert blocks[0]["is_error"] is True
    assert "not available in the investigation phase" in blocks[0]["content"]
    assert not (tool_workspace / "hack.py").exists()  # nothing was written
    assert "write_file" not in ctx.allowed_tool_names
