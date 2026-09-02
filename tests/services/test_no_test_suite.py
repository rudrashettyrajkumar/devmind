"""No test suite (E8-F1-T4) — the session proceeds as UNVERIFIED, not as passing.

`profile.has_test_suite is False` → nothing runs, no `TestRunModel` row is written, a
`TEST_RUN` event marks the skip, and the flow continues to `SUMMARIZING`. E9 surfaces
the UNVERIFIED flag in the approval payload.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, SessionStatus
from devmind.repositories import (
    EventRepository,
    SessionRepository,
    TestRunRepository,
)
from devmind.schemas.repo import RepoProfile
from devmind.schemas.session import SessionCreate
from devmind.services.pytest_output_parser import PytestOutputParser
from devmind.services.test_execution_service import TestExecutionService
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox, command_result
from tests.fakes.fake_workbench_builder import FakeRepoIngestionService, make_ingestion_result
from tests.services._agent_kit import build_orchestrator

_NO_SUITE = RepoProfile(language="python", test_command=(), has_test_suite=False)


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(repo_url="https://github.com/x/y", issue_description="no tests here")
    ).id


async def test_service_skips_and_never_reports_green(
    db_session: SQLAlchemySession, sid: str
) -> None:
    sandbox = FakeSandbox()
    svc = TestExecutionService(
        sandbox,
        PytestOutputParser(),
        TestRunRepository(db_session),
        EventRepository(db_session),
    )

    result = await svc.run_baseline(sid, _NO_SUITE)

    assert result.skipped is True
    assert result.verified_green is False
    assert sandbox.commands == []  # nothing executed
    assert TestRunRepository(db_session).list_for_session(sid) == []
    events = [
        e for e in EventRepository(db_session).list_since(sid) if e.event_type is EventType.TEST_RUN
    ]
    assert events and events[0].payload["skipped"] is True


async def test_orchestrator_reaches_summarizing_without_a_verdict(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    sandbox = FakeSandbox()
    sandbox.queue(
        command_result(stdout="diff --git a/README.md b/README.md\n-old\n+new\n"),  # git diff
    )
    ingestion_result = make_ingestion_result(sid, tool_workspace).model_copy(
        update={"profile": _NO_SUITE}
    )
    orchestrator, _ = build_orchestrator(
        db_session,
        ingestion=FakeRepoIngestionService(result=ingestion_result),
        loop_llm=FakeLLMProvider(
            [
                tool_call("finish", summary="Investigated; docs are stale", confidence=0.7),
                tool_call("finish", summary="Updated README", confidence=0.9),
            ]
        ),
        planner_llm=FakeLLMProvider(
            [
                tool_call(
                    "todo_write",
                    items=[
                        {"content": "Read the stale README section and the current behaviour"},
                        {"content": "Rewrite the README section to match current behaviour"},
                    ],
                )
            ]
        ),
        sandbox=sandbox,
    )

    await orchestrator.run(sid)

    assert session_repo.get_by_id(sid).status is SessionStatus.SUMMARIZING
    assert TestRunRepository(db_session).list_for_session(sid) == []  # no rows, ever
    transitions = [
        (e.payload["from"], e.payload["to"])
        for e in EventRepository(db_session).list_since(sid)
        if e.event_type is EventType.STATE_CHANGED
    ]
    assert transitions[-1] == ("testing", "summarizing")
