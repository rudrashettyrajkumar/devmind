"""`AgentLoop` — a cooperative cancellation is observed within one step (E7-F1-T5)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase, LoopStatus, SessionStatus
from devmind.interfaces.llm_provider import LLMProvider
from devmind.repositories import SessionRepository
from devmind.schemas.llm import LLMRequest, LLMResponse
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox
from tests.services._agent_kit import full_registry, make_context, make_loop, make_tool_context


class _HaltOnFirstCall(LLMProvider):
    """Flags the session HALTED the moment the loop makes its first call, so the
    cancellation is pending before step 2 begins.
    """

    def __init__(self, inner: FakeLLMProvider, sessions: SessionRepository, sid: str) -> None:
        self._inner = inner
        self._sessions = sessions
        self._sid = sid
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            self._sessions.update_status(self._sid, SessionStatus.HALTED)
        return await self._inner.complete(request)


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="bug")
    ).id


async def test_cancel_flag_ends_the_loop(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    inner = FakeLLMProvider([tool_call("list_dir", path=".") for _ in range(4)])
    llm = _HaltOnFirstCall(inner, session_repo, sid)
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.INVESTIGATION, step_budget=10)
    loop = make_loop(llm, db_session, registry)

    outcome = await loop.run(ctx, tctx, AgentPhase.INVESTIGATION)

    assert outcome.status is LoopStatus.CANCELLED
    assert outcome.steps_used == 1  # one step ran, then the cancel was seen
    assert llm.calls == 1
