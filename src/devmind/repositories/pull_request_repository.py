"""Data access for the delivered PR record. `PRService` (E10) is the only caller,
and only after a session's approval has been consumed.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from devmind.models.pull_request import PullRequestModel


class PullRequestRepository:
    """CRUD (create + read only) for `PullRequestModel`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, session_id: str, *, number: int, url: str, branch: str, head_sha: str
    ) -> PullRequestModel:
        model = PullRequestModel(
            session_id=session_id, number=number, url=url, branch=branch, head_sha=head_sha
        )
        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)
        return model

    def get_by_session(self, session_id: str) -> PullRequestModel | None:
        stmt = select(PullRequestModel).where(PullRequestModel.session_id == session_id)
        return self._session.execute(stmt).scalars().first()
