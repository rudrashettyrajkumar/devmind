"""Data access for the approval gate. `ApprovalService` (E9) is the only intended
caller; `PRService`'s `RemoteOperationGuard` (E9, E10) reads through here too, on
every attempt to open a PR — see SI-3 in docs/01-solution-design.md §3.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from devmind.core.enums import ApprovalDecision
from devmind.exceptions import RecordNotFoundError
from devmind.models.approval import ApprovalModel
from devmind.models.base import utcnow


class ApprovalRepository:
    """CRUD for `ApprovalModel`. One approval record per session (by convention;
    not DB-enforced here — `ApprovalService`, E9, owns the "only one open request at
    a time" rule).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, session_id: str, token: str) -> ApprovalModel:
        model = ApprovalModel(session_id=session_id, token=token)
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def get_by_session(self, session_id: str) -> ApprovalModel | None:
        stmt = (
            select(ApprovalModel)
            .where(ApprovalModel.session_id == session_id)
            .order_by(ApprovalModel.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    def get_by_token(self, token: str) -> ApprovalModel | None:
        stmt = select(ApprovalModel).where(ApprovalModel.token == token)
        return self._session.execute(stmt).scalars().first()

    def decide(
        self,
        session_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalModel:
        model = self._get_or_raise(session_id)
        model.decision = decision
        model.decided_by = decided_by
        model.reason = reason
        model.decided_at = utcnow()
        self._session.commit()
        self._session.refresh(model)
        return model

    def consume(self, session_id: str) -> ApprovalModel:
        model = self._get_or_raise(session_id)
        model.consumed_at = utcnow()
        self._session.commit()
        self._session.refresh(model)
        return model

    def _get_or_raise(self, session_id: str) -> ApprovalModel:
        model = self.get_by_session(session_id)
        if model is None:
            raise RecordNotFoundError(
                f"no approval record for session {session_id}",
                details={"session_id": session_id},
            )
        return model
