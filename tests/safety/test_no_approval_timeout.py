"""No auto-approve, no approval timeout — anywhere, ever.

`AWAITING_APPROVAL` is durable and waits forever. A timeout defaulting to "approve"
would silently void the entire safety model; one defaulting to "reject" is a feature
nobody asked for. This grep guards against a future "convenience" adding either.

A regression here is a broken invariant — fix the code, never the test.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "devmind"
# Identifier-style tokens only: prose like "no auto-approve" in a docstring is the
# invariant being *stated*, not a bypass being *implemented*.
_FORBIDDEN_TOKENS = ("auto_approve", "approval_timeout", "autoapprove")


def test_no_auto_approve_or_timeout_token_in_source() -> None:
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in _FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(_SRC)}: {token!r}")
    assert offenders == [], f"forbidden approval-bypass tokens found: {offenders}"
