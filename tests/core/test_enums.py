import pytest

from devmind.core.enums import (
    AgentPhase,
    ApprovalDecision,
    EventType,
    SandboxBackend,
    SessionStatus,
    StopReason,
    TodoStatus,
    ToolName,
)


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        (SessionStatus.CREATED, "created"),
        (SessionStatus.AWAITING_APPROVAL, "awaiting_approval"),
        (SessionStatus.PR_OPENED, "pr_opened"),
        (SessionStatus.REJECTED, "rejected"),
    ],
)
def test_session_status_values(member: SessionStatus, expected: str) -> None:
    assert member.value == expected


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        (SessionStatus.CREATED, False),
        (SessionStatus.AWAITING_APPROVAL, False),
        (SessionStatus.APPROVED, False),
        (SessionStatus.PR_OPENED, True),
        (SessionStatus.REJECTED, True),
        (SessionStatus.EXHAUSTED, True),
        (SessionStatus.FAILED, True),
        (SessionStatus.HALTED, True),
    ],
)
def test_is_terminal(member: SessionStatus, expected: bool) -> None:
    assert member.is_terminal() is expected


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (SessionStatus.CREATED, SessionStatus.INGESTING),
        (SessionStatus.INGESTING, SessionStatus.PLANNING),
        (SessionStatus.PLANNING, SessionStatus.INVESTIGATING),
        (SessionStatus.INVESTIGATING, SessionStatus.EDITING),
        (SessionStatus.EDITING, SessionStatus.TESTING),
        (SessionStatus.TESTING, SessionStatus.EDITING),
        (SessionStatus.TESTING, SessionStatus.SUMMARIZING),
        (SessionStatus.TESTING, SessionStatus.EXHAUSTED),
        (SessionStatus.SUMMARIZING, SessionStatus.AWAITING_APPROVAL),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.APPROVED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.REJECTED),
        (SessionStatus.APPROVED, SessionStatus.PR_OPENED),
        (SessionStatus.CREATED, SessionStatus.FAILED),
        (SessionStatus.CREATED, SessionStatus.HALTED),
    ],
)
def test_legal_transitions_are_allowed(source: SessionStatus, target: SessionStatus) -> None:
    assert source.can_transition_to(target) is True


@pytest.mark.parametrize(
    "source", [s for s in SessionStatus if s.is_terminal()], ids=lambda s: s.value
)
def test_terminal_statuses_accept_no_transition(source: SessionStatus) -> None:
    for target in SessionStatus:
        assert source.can_transition_to(target) is False


def test_every_illegal_pair_is_rejected() -> None:
    """Generated over the full cartesian product: adding a status without updating
    the legal-transition map fails this test.
    """
    legal_pairs = {
        (SessionStatus.CREATED, SessionStatus.INGESTING),
        (SessionStatus.CREATED, SessionStatus.FAILED),
        (SessionStatus.CREATED, SessionStatus.HALTED),
        (SessionStatus.INGESTING, SessionStatus.PLANNING),
        (SessionStatus.INGESTING, SessionStatus.FAILED),
        (SessionStatus.INGESTING, SessionStatus.HALTED),
        (SessionStatus.PLANNING, SessionStatus.INVESTIGATING),
        (SessionStatus.PLANNING, SessionStatus.FAILED),
        (SessionStatus.PLANNING, SessionStatus.HALTED),
        (SessionStatus.INVESTIGATING, SessionStatus.EDITING),
        (SessionStatus.INVESTIGATING, SessionStatus.FAILED),
        (SessionStatus.INVESTIGATING, SessionStatus.HALTED),
        (SessionStatus.EDITING, SessionStatus.TESTING),
        (SessionStatus.EDITING, SessionStatus.FAILED),
        (SessionStatus.EDITING, SessionStatus.HALTED),
        (SessionStatus.TESTING, SessionStatus.EDITING),
        (SessionStatus.TESTING, SessionStatus.SUMMARIZING),
        (SessionStatus.TESTING, SessionStatus.EXHAUSTED),
        (SessionStatus.TESTING, SessionStatus.FAILED),
        (SessionStatus.TESTING, SessionStatus.HALTED),
        (SessionStatus.SUMMARIZING, SessionStatus.AWAITING_APPROVAL),
        (SessionStatus.SUMMARIZING, SessionStatus.FAILED),
        (SessionStatus.SUMMARIZING, SessionStatus.HALTED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.APPROVED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.REJECTED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.HALTED),
        (SessionStatus.APPROVED, SessionStatus.PR_OPENED),
        (SessionStatus.APPROVED, SessionStatus.FAILED),
    }
    all_pairs = {(s, t) for s in SessionStatus for t in SessionStatus}
    for source, target in all_pairs - legal_pairs:
        assert source.can_transition_to(target) is False, f"{source} -> {target} should be illegal"
    for source, target in legal_pairs:
        assert source.can_transition_to(target) is True, f"{source} -> {target} should be legal"


def test_pr_opened_is_reachable_only_from_approved() -> None:
    """Structural proof of design §9 safety layer 2: no status other than APPROVED
    may legally transition to PR_OPENED.
    """
    sources_that_reach_pr_opened = [
        s for s in SessionStatus if s.can_transition_to(SessionStatus.PR_OPENED)
    ]
    assert sources_that_reach_pr_opened == [SessionStatus.APPROVED]


def test_event_type_members_are_strings() -> None:
    assert EventType.LLM_CALL.value == "llm_call"
    assert EventType.SESSION_FAILED.value == "session_failed"


def test_todo_status_members() -> None:
    assert {m.value for m in TodoStatus} == {"pending", "in_progress", "done", "skipped"}


def test_approval_decision_members() -> None:
    assert {m.value for m in ApprovalDecision} == {"approved", "rejected"}


def test_sandbox_backend_members() -> None:
    assert {m.value for m in SandboxBackend} == {"auto", "docker", "subprocess"}


def test_agent_phase_members() -> None:
    assert {m.value for m in AgentPhase} == {
        "planning",
        "investigation",
        "editing",
        "testing",
        "summarizing",
    }


def test_tool_name_members_are_complete() -> None:
    expected = {
        "list_dir",
        "read_file",
        "search_code",
        "find_symbol",
        "write_file",
        "apply_patch",
        "run_command",
        "run_tests",
        "git_diff",
        "todo_write",
        "finish",
    }
    assert {m.value for m in ToolName} == expected


def test_stop_reason_members() -> None:
    assert {m.value for m in StopReason} == {
        "end_turn",
        "tool_use",
        "max_tokens",
        "pause_turn",
        "refusal",
        "stop_sequence",
    }
