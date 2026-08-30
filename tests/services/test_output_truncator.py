from __future__ import annotations

import pytest

from devmind.services.output_truncator import OutputTruncator


def test_short_text_is_returned_unchanged() -> None:
    truncator = OutputTruncator(100)
    text = "a" * 50
    assert truncator.truncate(text) == (text, False)


def test_text_at_the_limit_is_not_truncated() -> None:
    truncator = OutputTruncator(100)
    text = "a" * 100
    assert truncator.truncate(text) == (text, False)


def test_long_text_keeps_head_and_tail_with_a_marker() -> None:
    truncator = OutputTruncator(20)
    text = "HEAD" + "x" * 200 + "TAIL"
    out, was_truncated = truncator.truncate(text)
    assert was_truncated is True
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert "truncated" in out
    assert f"of {len(text)} chars" in out


def test_marker_reports_the_removed_count() -> None:
    truncator = OutputTruncator(10)
    text = "y" * 1000
    out, _ = truncator.truncate(text)
    # 10 chars retained (5 head + 5 tail), 990 removed
    assert "truncated 990 of 1000 chars" in out


def test_pytest_summary_at_the_tail_survives() -> None:
    truncator = OutputTruncator(200)
    body = "collecting ... " + "noise " * 500
    summary = "\n=== 3 failed, 7 passed in 2.10s ==="
    out, was_truncated = truncator.truncate(body + summary)
    assert was_truncated is True
    assert "3 failed, 7 passed" in out


def test_zero_max_chars_is_rejected() -> None:
    with pytest.raises(ValueError):
        OutputTruncator(0)
