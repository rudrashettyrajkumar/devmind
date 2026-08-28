import pytest

from devmind.exceptions import (
    ApprovalAlreadyConsumedError,
    ApprovalRequiredError,
    BudgetExceededError,
    ConfigurationError,
    DevMindError,
    GitHubError,
    InvalidStateTransitionError,
    LLMProviderError,
    PathEscapeError,
    RepositoryIngestionError,
    SandboxError,
    SandboxTimeoutError,
    ToolExecutionError,
    WorkspaceError,
)


def test_base_error_carries_message_and_details() -> None:
    err = DevMindError("something broke", details={"session_id": "abc"})
    assert err.message == "something broke"
    assert err.details == {"session_id": "abc"}
    assert str(err) == "something broke"


def test_details_defaults_to_empty_dict() -> None:
    assert DevMindError("x").details == {}


@pytest.mark.parametrize(
    ("exc_type", "expected_status"),
    [
        (ConfigurationError, 500),
        (WorkspaceError, 500),
        (PathEscapeError, 400),
        (SandboxError, 500),
        (SandboxTimeoutError, 504),
        (LLMProviderError, 502),
        (ToolExecutionError, 500),
        (InvalidStateTransitionError, 409),
        (ApprovalRequiredError, 403),
        (ApprovalAlreadyConsumedError, 409),
        (BudgetExceededError, 402),
        (GitHubError, 502),
        (RepositoryIngestionError, 422),
    ],
)
def test_http_status_mapping(exc_type: type[DevMindError], expected_status: int) -> None:
    assert exc_type("x").http_status == expected_status


def test_all_subclasses_are_devmind_errors() -> None:
    for exc_type in (
        ConfigurationError,
        WorkspaceError,
        PathEscapeError,
        SandboxError,
        SandboxTimeoutError,
        LLMProviderError,
        ToolExecutionError,
        InvalidStateTransitionError,
        ApprovalRequiredError,
        ApprovalAlreadyConsumedError,
        BudgetExceededError,
        GitHubError,
        RepositoryIngestionError,
    ):
        assert issubclass(exc_type, DevMindError)


def test_path_escape_is_a_workspace_error() -> None:
    assert issubclass(PathEscapeError, WorkspaceError)


def test_sandbox_timeout_is_a_sandbox_error() -> None:
    assert issubclass(SandboxTimeoutError, SandboxError)
