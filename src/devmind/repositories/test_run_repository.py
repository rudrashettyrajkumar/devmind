"""Data access for test-suite executions. `TestExecutionService` (E8) is the caller;
rows here are immutable once created — the self-correction loop reads history, it
never edits a past attempt.
"""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from devmind.models.test_run import TestRunModel


class TestRunRepository:
    """CRUD (create + read only — see the module docstring) for `TestRunModel`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        session_id: str,
        *,
        attempt: int,
        is_baseline: bool,
        exit_code: int,
        passed: int,
        failed: int,
        errors: int,
        signature: str | None,
        report: Mapping[str, object],
        duration_seconds: float,
    ) -> TestRunModel:
        model = TestRunModel(
            session_id=session_id,
            attempt=attempt,
            is_baseline=is_baseline,
            exit_code=exit_code,
            passed=passed,
            failed=failed,
            errors=errors,
            signature=signature,
            report=dict(report),
            duration_seconds=duration_seconds,
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def list_for_session(self, session_id: str) -> list[TestRunModel]:
        stmt = (
            select(TestRunModel)
            .where(TestRunModel.session_id == session_id)
            .order_by(TestRunModel.created_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def latest_for_session(self, session_id: str) -> TestRunModel | None:
        stmt = (
            select(TestRunModel)
            .where(TestRunModel.session_id == session_id)
            .order_by(TestRunModel.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def baseline_for_session(self, session_id: str) -> TestRunModel | None:
        """The pre-flight run recorded on the clean checkout, if one happened. Its
        failures are the pre-existing set `TestExecutionService` subtracts from every
        later verdict.
        """
        stmt = (
            select(TestRunModel)
            .where(
                TestRunModel.session_id == session_id,
                TestRunModel.is_baseline.is_(True),
            )
            .order_by(TestRunModel.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def attempts_for_session(self, session_id: str) -> list[TestRunModel]:
        """Every non-baseline run for the session, oldest first. `SelfCorrectionController`
        reads the previous run's `signature` from the tail of this list.
        """
        stmt = (
            select(TestRunModel)
            .where(
                TestRunModel.session_id == session_id,
                TestRunModel.is_baseline.is_(False),
            )
            .order_by(TestRunModel.created_at, TestRunModel.attempt)
        )
        return list(self._session.execute(stmt).scalars().all())
