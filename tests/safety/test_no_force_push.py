"""E10-F3: no force-push, no branch delete, no remote retry.

`GitService.push` is the only remote-writing git call in the codebase. It must never
carry a force flag, a `+refs/…` refspec, or a branch delete — and a failed push must
not be retried in a loop. Grep- and structure-asserted so a regression fails CI. A
failure here is a broken invariant: fix the code, never the test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")
_GIT_SERVICE = Path(_SRC) / "devmind" / "services" / "git_service.py"

_FORBIDDEN = (
    "--force",
    "force-with-lease",
    "push --delete",
    "push -d",
)


def test_no_force_or_delete_flag_anywhere_in_src() -> None:
    for needle in _FORBIDDEN:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", needle, _SRC],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"{needle!r} found in src/:\n{result.stdout}"


def test_push_argv_is_exactly_set_upstream() -> None:
    text = _GIT_SERVICE.read_text(encoding="utf-8")
    assert '["git", "push", "--set-upstream", "origin", branch]' in text


def test_push_body_has_no_retry_loop() -> None:
    text = _GIT_SERVICE.read_text(encoding="utf-8")
    start = text.index("async def push(")
    # end at the next method definition, so only push()'s own body is inspected
    end = text.index("\n    async def ", start + 1)
    body = text[start:end]
    assert "for " not in body
    assert "while " not in body
