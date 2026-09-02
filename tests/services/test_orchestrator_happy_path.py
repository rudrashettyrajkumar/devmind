"""`SessionOrchestrator` — a scripted session runs CREATED -> ... -> SUMMARIZING with
the right transitions in order, a read-only investigation, a writable editing phase,
a pre-flight baseline run, and a green verdict (E7-F3 + E8 integration)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, SessionStatus, ToolName
from devmind.repositories import EventRepository, SessionRepository, TestRunRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox, command_result
from tests.fakes.fake_workbench_builder import FakeRepoIngestionService, make_ingestion_result
from tests.services._agent_kit import build_orchestrator

_PLAN = [
    {"content": "Read src/pkg/calc.py and confirm add() subtracts", "status": "pending"},
    {"content": "Change the operator in add() from minus to plus", "status": "pending"},
    {"content": "Run the pytest suite and confirm it is green", "status": "pending"},
]

_GREEN = "..  [100%]\n2 passed in 0.02s\n"


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(
            repo_url="https://github.com/x/y",
            issue_description="Calculator.add returns a - b",
        )
    ).id


async def test_full_happy_path_to_summarizing(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    sandbox = FakeSandbox()
    sandbox.queue(
        command_result(stdout=_GREEN),  # baseline: clean checkout is green
        command_result(
            stdout="diff --git a/src/pkg/calc.py b/src/pkg/calc.py\n-a - b\n+a + b\n"
        ),  # git diff after editing
        command_result(stdout=_GREEN),  # attempt 1: green
    )
    ingestion = FakeRepoIngestionService(result=make_ingestion_result(sid, tool_workspace))
    planner_llm = FakeLLMProvider([tool_call("todo_write", items=_PLAN)])
    loop_llm = FakeLLMProvider(
        [
            tool_call("finish", summary="Root cause: calc.py add() subtracts", confidence=0.85),
            tool_call("finish", summary="Edited src/pkg/calc.py: - to +", confidence=0.95),
        ]
    )
    orchestrator, workbench_builder = build_orchestrator(
        db_session,
        ingestion=ingestion,
        loop_llm=loop_llm,
        planner_llm=planner_llm,
        sandbox=sandbox,
    )

    await orchestrator.run(sid)

    assert session_repo.get_by_id(sid).status is SessionStatus.SUMMARIZING

    transitions = [
        (e.payload["from"], e.payload["to"])
        for e in EventRepository(db_session).list_since(sid)
        if e.event_type is EventType.STATE_CHANGED
    ]
    assert transitions == [
        ("created", "ingesting"),
        ("ingesting", "planning"),
        ("planning", "investigating"),
        ("investigating", "editing"),
        ("editing", "testing"),
        ("testing", "summarizing"),
    ]

    # investigation call saw only read-only tools; editing call could write.
    investigation_tools = {t["name"] for t in loop_llm.requests[0].tools}
    editing_tools = {t["name"] for t in loop_llm.requests[1].tools}
    assert ToolName.WRITE_FILE.value not in investigation_tools
    assert ToolName.APPLY_PATCH.value not in investigation_tools
    assert ToolName.RUN_COMMAND.value not in investigation_tools
    assert ToolName.WRITE_FILE.value in editing_tools

    # one baseline run + one attempt run, both recorded.
    runs = TestRunRepository(db_session).list_for_session(sid)
    assert [r.is_baseline for r in runs] == [True, False]
    assert runs[1].failed == 0

    assert workbench_builder.built == [sid]
    assert sandbox.teardown_calls == 1  # cleanup ran
