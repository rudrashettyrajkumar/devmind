"""`AgentLoop` — crossing the session cost ceiling raises `BudgetExceededError`
before the next call is made (E7-F3-T5)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase
from devmind.exceptions import BudgetExceededError
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


async def test_cost_ceiling_halts_the_loop(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    session_repo.record_usage(
        sid, input_tokens=0, output_tokens=0, cache_read_tokens=0, cost_usd=9.99
    )
    llm = FakeLLMProvider([tool_call("list_dir", path=".")])
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.EDITING)
    loop = make_loop(llm, db_session, registry, cost_ceiling_usd=5.0)

    with pytest.raises(BudgetExceededError):
        await loop.run(ctx, tctx, AgentPhase.EDITING)

    assert llm.call_count == 0  # the ceiling check runs before the model call
