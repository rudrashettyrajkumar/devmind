"""`PlannerService` — a valid plan is persisted and versioned; a one-line plan is
retried once and then fails the session (E7-F2)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType
from devmind.exceptions import PlanningError
from devmind.prompts.loader import PromptLoader
from devmind.repositories import EventRepository, SessionRepository, TodoRepository
from devmind.schemas.session import SessionCreate, SessionRead
from devmind.services.planner_service import PlannerService
from tests.fakes.fake_llm_provider import FakeLLMProvider, final_text, tool_call
from tests.fakes.fake_workbench_builder import make_repo_brief

_GOOD_PLAN = [
    {"content": "Read src/sample/calc.py and confirm add() subtracts", "status": "pending"},
    {"content": "Change the minus operator in add() to a plus", "status": "pending"},
    {"content": "Run the pytest suite and confirm test_add passes", "status": "pending"},
]
_TWO_STEP_PLAN = [
    {"content": "Locate the faulty operator in calc.py add()", "status": "pending"},
    {"content": "Fix the operator and re-run the suite", "status": "pending"},
]
_ONE_LINER = [{"content": "fix the bug", "status": "pending"}]


@pytest.fixture
def session(session_repo: SessionRepository) -> SessionRead:
    model = session_repo.create(
        SessionCreate(
            repo_url="https://github.com/x/y",
            issue_description="Calculator.add returns a - b instead of a + b",
        )
    )
    return SessionRead.model_validate(model)


def _planner(llm: FakeLLMProvider, db_session: SQLAlchemySession) -> PlannerService:
    return PlannerService(
        llm, PromptLoader(), TodoRepository(db_session), EventRepository(db_session)
    )


async def test_valid_plan_is_persisted_and_a_plan_updated_event_emitted(
    db_session: SQLAlchemySession, session: SessionRead
) -> None:
    llm = FakeLLMProvider([tool_call("todo_write", items=_GOOD_PLAN)])
    plan = await _planner(llm, db_session).create_plan(session, make_repo_brief())

    assert [item.content for item in plan] == [step["content"] for step in _GOOD_PLAN]
    persisted = TodoRepository(db_session).list_for_session(session.id)
    assert len(persisted) == 3

    events = EventRepository(db_session).list_since(session.id)
    plan_events = [e for e in events if e.event_type is EventType.PLAN_UPDATED]
    assert len(plan_events) == 1
    assert plan_events[0].payload["version"] == 1


async def test_one_line_plan_is_retried_then_accepted(
    db_session: SQLAlchemySession, session: SessionRead
) -> None:
    llm = FakeLLMProvider(
        [tool_call("todo_write", items=_ONE_LINER), tool_call("todo_write", items=_TWO_STEP_PLAN)]
    )
    plan = await _planner(llm, db_session).create_plan(session, make_repo_brief())

    assert len(plan) == 2
    assert llm.call_count == 2  # one rejection, one retry


async def test_still_bad_after_retry_raises_planning_error(
    db_session: SQLAlchemySession, session: SessionRead
) -> None:
    llm = FakeLLMProvider(
        [tool_call("todo_write", items=_ONE_LINER), tool_call("todo_write", items=_ONE_LINER)]
    )
    with pytest.raises(PlanningError):
        await _planner(llm, db_session).create_plan(session, make_repo_brief())
    assert llm.call_count == 2
    assert TodoRepository(db_session).list_for_session(session.id) == []


async def test_planner_that_never_calls_todo_write_fails(
    db_session: SQLAlchemySession, session: SessionRead
) -> None:
    llm = FakeLLMProvider([final_text("here is a plan in prose"), final_text("still prose")])
    with pytest.raises(PlanningError):
        await _planner(llm, db_session).create_plan(session, make_repo_brief())
