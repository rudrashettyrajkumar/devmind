"""`SelfCorrectionController.decide()` (E8-F3) — pass first try, pass on attempt 2,
exhaust at the attempt cap, and early-exhaust on a repeated failure signature.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.constants import MAX_FIX_ATTEMPTS
from devmind.core.enums import CorrectionAction, EventType
from devmind.repositories import EventRepository, SessionRepository, TestRunRepository
from devmind.schemas.session import SessionCreate
from devmind.schemas.test_execution import CorrectionDecision, TestFailure, TestFailureReport
from devmind.services.self_correction_controller import SelfCorrectionController


@pytest.fixture
def session_id(session_repo: SessionRepository) -> str:
    return session_repo.create(SessionCreate(repo_url="https://github.com/a/b", issue_number=1)).id


@pytest.fixture
def controller(db_session: SQLAlchemySession) -> SelfCorrectionController:
    return SelfCorrectionController(TestRunRepository(db_session), EventRepository(db_session))


def _red(signature: str, *, failed: int = 1) -> TestFailureReport:
    return TestFailureReport(
        total=failed,
        failed=failed,
        failures=tuple(
            TestFailure(node_id=f"t/test.py::test_{i}", exception_type="AssertionError")
            for i in range(failed)
        ),
        signature=signature,
    )


def _green() -> TestFailureReport:
    return TestFailureReport(total=5, passed=5, signature=TestFailureReport.signature_for([]))


def _persist(repo: TestRunRepository, session_id: str, attempt: int, signature: str) -> None:
    repo.create(
        session_id,
        attempt=attempt,
        is_baseline=False,
        exit_code=1,
        passed=0,
        failed=1,
        errors=0,
        signature=signature,
        report={},
        duration_seconds=1.0,
    )


def test_pass_first_try(controller: SelfCorrectionController, session_id: str) -> None:
    decision = controller.decide(session_id, _green(), attempt=1)
    assert decision.action is CorrectionAction.SUCCEEDED


def test_pass_on_attempt_two(
    controller: SelfCorrectionController, session_id: str, db_session: SQLAlchemySession
) -> None:
    _persist(TestRunRepository(db_session), session_id, attempt=1, signature="sig-a")
    decision = controller.decide(session_id, _green(), attempt=2)
    assert decision.action is CorrectionAction.SUCCEEDED


def test_retry_while_progressing_and_under_budget(
    controller: SelfCorrectionController, session_id: str, db_session: SQLAlchemySession
) -> None:
    runs = TestRunRepository(db_session)
    _persist(runs, session_id, attempt=1, signature="sig-a")
    _persist(runs, session_id, attempt=2, signature="sig-b")  # the run just executed
    decision = controller.decide(session_id, _red("sig-b"), attempt=2)
    assert decision.action is CorrectionAction.RETRY
    assert decision.attempts_remaining == MAX_FIX_ATTEMPTS - 2


def test_exhaust_at_the_attempt_cap(
    controller: SelfCorrectionController, session_id: str, db_session: SQLAlchemySession
) -> None:
    runs = TestRunRepository(db_session)
    _persist(runs, session_id, attempt=1, signature="sig-a")
    _persist(runs, session_id, attempt=2, signature="sig-b")
    _persist(runs, session_id, attempt=3, signature="sig-c")
    decision = controller.decide(session_id, _red("sig-c"), attempt=MAX_FIX_ATTEMPTS)
    assert decision.action is CorrectionAction.EXHAUSTED
    assert "budget" in decision.reason
    assert decision.attempts_remaining == 0


def test_early_exhaust_on_repeated_signature(
    controller: SelfCorrectionController, session_id: str, db_session: SQLAlchemySession
) -> None:
    runs = TestRunRepository(db_session)
    _persist(runs, session_id, attempt=1, signature="sig-stuck")
    _persist(runs, session_id, attempt=2, signature="sig-stuck")  # the run just executed
    decision = controller.decide(session_id, _red("sig-stuck"), attempt=2)
    assert decision.action is CorrectionAction.EXHAUSTED
    assert "no progress" in decision.reason


def test_record_attempt_emits_fix_attempt_event(
    controller: SelfCorrectionController, session_id: str, db_session: SQLAlchemySession
) -> None:
    decision = CorrectionDecision(
        action=CorrectionAction.RETRY, reason="one failing", attempts_remaining=2
    )
    controller.record_attempt(session_id, attempt=1, signature="sig-x", decision=decision)
    events = [
        e
        for e in EventRepository(db_session).list_since(session_id)
        if e.event_type is EventType.FIX_ATTEMPT
    ]
    assert len(events) == 1
    assert events[0].payload["signature"] == "sig-x"
    assert events[0].payload["action"] == "retry"
