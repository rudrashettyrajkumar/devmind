"""`AgentLoop` — the assistant turn is appended verbatim and every parallel tool
result lands in ONE user message (E7-F1-T2, the two rules from spec §AgentContext)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import AgentPhase
from devmind.repositories import SessionRepository
from devmind.schemas.llm import ToolCall
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text, tool_calls
from tests.fakes.fake_sandbox import FakeSandbox
from tests.services._agent_kit import full_registry, make_context, make_loop, make_tool_context


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="bug")
    ).id


async def test_batched_results_are_one_user_message(
    db_session: SQLAlchemySession, tool_workspace, sid: str
) -> None:
    batched = tool_calls(
        ToolCall(id="c1", name="list_dir", arguments={"path": "."}),
        ToolCall(id="c2", name="read_file", arguments={"path": "README.md"}),
    )
    llm = FakeLLMProvider([batched, final_text("ok")])
    registry = full_registry()
    tctx = make_tool_context(db_session, tool_workspace, sid, FakeSandbox())
    ctx = make_context(registry, sid, AgentPhase.INVESTIGATION)
    loop = make_loop(llm, db_session, registry)

    await loop.run(ctx, tctx, AgentPhase.INVESTIGATION)

    messages = ctx.messages
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == batched.raw_content  # verbatim, not rebuilt from text

    user_turn = messages[2]
    assert user_turn["role"] == "user"
    blocks = user_turn["content"]
    assert isinstance(blocks, list)
    assert len(blocks) == 2
    assert all(block["type"] == "tool_result" for block in blocks)

    # the second request the model saw carries that single combined user message
    second_request = llm.requests[1]
    assert second_request.messages[-1]["role"] == "user"
    assert len(second_request.messages[-1]["content"]) == 2
