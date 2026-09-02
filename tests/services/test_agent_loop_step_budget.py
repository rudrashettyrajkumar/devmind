"""`AgentLoop` — halts exactly at the step budget with `BUDGET_EXHAUSTED` (E7-F1-T3)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase, LoopStatus
from devmind.repositories import SessionRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.services._agent_kit import full_registry, make_context, make_loop, make_tool_context


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="bug")
    ).id


async def test_loop_stops_at_the_budget(
    db_session: SQLAlchemySession, tool_workspace, sid: str
) -> None:
    # More scripted steps than the budget allows.
    llm = FakeLLMProvider([tool_call("list_dir", path=".") for _ in range(5)])
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.EDITING, step_budget=2)
    loop = make_loop(llm, db_session, registry)

    outcome = await loop.run(ctx, tctx, AgentPhase.EDITING)

    assert outcome.status is LoopStatus.BUDGET_EXHAUSTED
    assert outcome.steps_used == 2
    assert llm.call_count == 2  # not one call more
    assert ctx.remaining_steps == 0
