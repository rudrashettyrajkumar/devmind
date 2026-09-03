"""SI-6: PRs are always opened as drafts, never merged.

There is no merge code path anywhere in `src/`. This is asserted by grep so that a
future well-meaning "just auto-merge the trivial ones" change fails CI immediately.
A regression here is a broken invariant — fix the code, never the test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")

_FORBIDDEN = ("pr merge", "--auto-merge", "gh pr merge", "merge_pull_request")


def test_si6_no_merge_call_exists_in_src() -> None:
    for needle in _FORBIDDEN:
        result = subprocess.run(
            ["grep", "-rn", needle, _SRC],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"{needle!r} found in src/:\n{result.stdout}"
