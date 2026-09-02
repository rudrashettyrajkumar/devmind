"""The epic's proof (E8-F3-T5): a seeded failing repo driven red -> green through the
orchestrator, and a stuck repo short-circuited to EXHAUSTED.

`FakeLLMProvider` scripts the phases; `FakeSandbox` scripts the pytest runs. The
assertions are on the persisted state path, not on prose.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import MAX_FIX_ATTEMPTS
from devmind.core.enums import EventType, SessionStatus
from devmind.repositories import EventRepository, SessionRepository, TestRunRepository
from devmind.schemas.session import SessionCreate
from tests.fakes.fake_llm_provider import FakeLLMProvider, tool_call
from tests.fakes.fake_sandbox import FakeSandbox, command_result
from tests.fakes.fake_workbench_builder import FakeRepoIngestionService, make_ingestion_result
from tests.services._agent_kit import build_orchestrator

_GREEN = command_result(stdout="..  [100%]\n2 passed in 0.05s\n")
_RED = command_result(
    exit_code=1,
    stdout=(
        ".F  [100%]\n"
        "=================================== FAILURES ===================================\n"
        "______________________________ test_divide ______________________________\n"
        "tests/test_calc.py:8: in test_divide\n"
        "    assert divide(10, 2) == 5\n"
        "E   assert 4 == 5\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_calc.py::test_divide - assert 4 == 5\n"
        "1 failed, 1 passed in 0.06s\n"
    ),
)
_DIFF = command_result(stdout="diff --git a/src/calc.py b/src/calc.py\n-  wrong\n+  right\n")

_PLAN = [
    {"content": "Locate the off-by-one in divide() and correct it"},
    {"content": "Run the pytest suite and confirm divide() is green"},
]


@pytest.fixture
def sid(session_repo: SessionRepository) -> str:
    return session_repo.create(
        SessionCreate(
            repo_url="https://github.com/x/y",
            issue_description="divide() is off by one",
        )
    ).id


def _state_path(db_session: SQLAlchemySession, sid: str) -> list[tuple[str, str]]:
    return [
        (e.payload["from"], e.payload["to"])
        for e in EventRepository(db_session).list_since(sid)
        if e.event_type is EventType.STATE_CHANGED
    ]


async def test_red_to_green_on_the_second_attempt(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    sandbox = FakeSandbox(default=_GREEN)
    sandbox.queue(
        _GREEN,  # 1. baseline — clean checkout is green
        _DIFF,  # 2. git diff after editing phase 1
        _RED,  # 3. attempt 1 (full) — the first patch was buggy
        _DIFF,  # 4. git diff for the retry prompt
        _DIFF,  # 5. git diff for the retry empty-check
        _GREEN,  # 6. attempt 2 (targeted at test_divide) — green
        _GREEN,  # 7. attempt 2 (full confirm before the gate) — green
    )
    orchestrator, _ = build_orchestrator(
        db_session,
        ingestion=FakeRepoIngestionService(result=make_ingestion_result(sid, tool_workspace)),
        loop_llm=FakeLLMProvider(
            [
                tool_call("finish", summary="Root cause: divide truncates", confidence=0.8),
                tool_call("finish", summary="First patch to divide()", confidence=0.7),
                tool_call("finish", summary="Corrected the rounding in divide()", confidence=0.95),
            ]
        ),
        planner_llm=FakeLLMProvider([tool_call("todo_write", items=_PLAN)]),
        sandbox=sandbox,
    )

    await orchestrator.run(sid)

    session = session_repo.get_by_id(sid)
    assert session.status is SessionStatus.SUMMARIZING
    assert session.fix_attempts == 1
    assert session.fix_attempts <= MAX_FIX_ATTEMPTS

    path = _state_path(db_session, sid)
    assert path[-3:] == [
        ("testing", "editing"),
        ("editing", "testing"),
        ("testing", "summarizing"),
    ]

    fix_events = [
        e
        for e in EventRepository(db_session).list_since(sid)
        if e.event_type is EventType.FIX_ATTEMPT
    ]
    assert [e.payload["action"] for e in fix_events] == ["retry"]

    runs = TestRunRepository(db_session).list_for_session(sid)
    assert [r.is_baseline for r in runs] == [True, False, False, False]
    assert runs[-1].failed == 0  # the run that precedes SUMMARIZING is a full green run


async def test_identical_signature_short_circuits_to_exhausted(
    db_session: SQLAlchemySession, session_repo: SessionRepository, tool_workspace, sid: str
) -> None:
    sandbox = FakeSandbox(default=_RED)
    sandbox.queue(
        _GREEN,  # 1. baseline
        _DIFF,  # 2. git diff after editing phase 1
        _RED,  # 3. attempt 1 (full) — red
        _DIFF,  # 4. git diff for the retry prompt
        _DIFF,  # 5. git diff for the retry empty-check
        _RED,  # 6. attempt 2 — the retry changed nothing that mattered: same failure
    )
    orchestrator, _ = build_orchestrator(
        db_session,
        ingestion=FakeRepoIngestionService(result=make_ingestion_result(sid, tool_workspace)),
        loop_llm=FakeLLMProvider(
            [
                tool_call("finish", summary="Root cause hypothesis", confidence=0.6),
                tool_call("finish", summary="Patch attempt 1", confidence=0.6),
                tool_call("finish", summary="Patch attempt 2 (same idea)", confidence=0.5),
            ]
        ),
        planner_llm=FakeLLMProvider([tool_call("todo_write", items=_PLAN)]),
        sandbox=sandbox,
    )

    await orchestrator.run(sid)

    session = session_repo.get_by_id(sid)
    assert session.status is SessionStatus.EXHAUSTED
    assert session.failure_reason is not None and "no progress" in session.failure_reason
    assert session.fix_attempts == 1  # only one retry happened before the short-circuit

    path = _state_path(db_session, sid)
    assert ("testing", "exhausted") in path
    assert ("editing", "testing") in path  # it did loop back once
