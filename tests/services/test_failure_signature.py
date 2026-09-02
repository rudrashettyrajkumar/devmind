"""The failure signature (E8-F2-T2) — what makes no-progress detection possible.

`signature = sha256(sorted("node_id:exception_type"))`: stable across re-runs,
insensitive to ordering and to line-number drift, sensitive to a genuinely
different failure set.
"""

from __future__ import annotations

from devmind.schemas.test_execution import TestFailure, TestFailureReport


def _failure(node_id: str, exc: str | None, line: int) -> TestFailure:
    return TestFailure(node_id=node_id, exception_type=exc, line=line, message="x")


def test_stable_across_identical_reruns() -> None:
    failures = [_failure("t/a.py::test_x", "AssertionError", 10)]
    first = TestFailureReport.signature_for(failures)
    second = TestFailureReport.signature_for(list(failures))
    assert first == second


def test_order_insensitive() -> None:
    a = _failure("t/a.py::test_a", "AssertionError", 1)
    b = _failure("t/b.py::test_b", "ValueError", 2)
    assert TestFailureReport.signature_for([a, b]) == TestFailureReport.signature_for([b, a])


def test_insensitive_to_line_number_drift() -> None:
    before = [_failure("t/a.py::test_x", "AssertionError", 10)]
    after = [_failure("t/a.py::test_x", "AssertionError", 42)]
    assert TestFailureReport.signature_for(before) == TestFailureReport.signature_for(after)


def test_changes_when_a_failure_is_fixed() -> None:
    two = [
        _failure("t/a.py::test_a", "AssertionError", 1),
        _failure("t/b.py::test_b", "ValueError", 2),
    ]
    one = [_failure("t/a.py::test_a", "AssertionError", 1)]
    assert TestFailureReport.signature_for(two) != TestFailureReport.signature_for(one)


def test_changes_when_the_exception_type_changes() -> None:
    assertion = [_failure("t/a.py::test_a", "AssertionError", 1)]
    type_error = [_failure("t/a.py::test_a", "TypeError", 1)]
    assert TestFailureReport.signature_for(assertion) != TestFailureReport.signature_for(type_error)


def test_empty_failure_set_is_deterministic() -> None:
    assert TestFailureReport.signature_for([]) == TestFailureReport.signature_for([])
