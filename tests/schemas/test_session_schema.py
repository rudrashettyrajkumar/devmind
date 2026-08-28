import pytest
from pydantic import ValidationError

from devmind.schemas.session import SessionCreate


def test_valid_with_issue_number() -> None:
    data = SessionCreate(repo_url="https://github.com/a/b", issue_number=42)
    assert data.issue_number == 42
    assert data.issue_description is None


def test_valid_with_issue_description() -> None:
    data = SessionCreate(repo_url="https://github.com/a/b", issue_description="fix the bug")
    assert data.issue_description == "fix the bug"
    assert data.issue_number is None


def test_valid_with_ssh_repo_url() -> None:
    data = SessionCreate(repo_url="git@github.com:a/b.git", issue_number=1)
    assert data.repo_url == "git@github.com:a/b.git"


def test_neither_issue_input_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SessionCreate(repo_url="https://github.com/a/b")


def test_both_issue_inputs_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SessionCreate(
            repo_url="https://github.com/a/b", issue_number=1, issue_description="also this"
        )


@pytest.mark.parametrize("bad_url", ["not-a-url", "ftp://example.com/repo", "", "just some text"])
def test_bad_repo_url_rejected(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        SessionCreate(repo_url=bad_url, issue_number=1)


def test_issue_number_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SessionCreate(repo_url="https://github.com/a/b", issue_number=0)
