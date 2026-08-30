from __future__ import annotations

import pytest
from pydantic import ValidationError

from devmind.core.enums import IssueState
from devmind.schemas.github import IssueRead


def test_minimal_issue() -> None:
    issue = IssueRead(number=1, title="t", state=IssueState.OPEN)
    assert issue.body == ""
    assert issue.labels == ()


def test_state_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError):
        IssueRead(number=1, title="t", state="pending")  # type: ignore[arg-type]


def test_labels_round_trip_as_tuple() -> None:
    issue = IssueRead(number=1, title="t", labels=("bug", "ux"), state=IssueState.CLOSED)
    assert issue.labels == ("bug", "ux")
