"""SI-4 at the E10 boundary: the approval token is single-use. A second
`open_draft_pr` on the same session raises `ApprovalAlreadyConsumedError` and opens
nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.exceptions import ApprovalAlreadyConsumedError
from tests.services._pr_kit import build_harness


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


async def test_second_open_draft_pr_is_rejected(
    db_session: SQLAlchemySession, workspace: Path
) -> None:
    h = await build_harness(db_session, workspace)

    first = await h.service.open_draft_pr(h.session_id)
    assert first.number == 7
    calls_after_first = len(h.runner.calls)

    with pytest.raises(ApprovalAlreadyConsumedError):
        await h.service.open_draft_pr(h.session_id)

    # nothing new ran, and there is still exactly one PR row
    assert len(h.runner.calls) == calls_after_first
    assert h.prs.get_by_session(h.session_id) is not None
