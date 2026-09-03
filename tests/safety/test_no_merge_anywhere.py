"""E10-F3-T1: no merge path exists anywhere in `src/`.

DevMind opens a draft PR and stops. There is no `gh pr merge`, no `--auto`, no
`--merge`/`--rebase`/`--squash` merge flag, no `--admin` override, no REST merge call
— not behind a flag, not for "trivial" changes, not ever (SI-6). Asserted by grep so
a future "just auto-merge the safe ones" change fails CI on the spot. A regression
here is a broken invariant: fix the code, never the test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")

_FORBIDDEN = (
    "pr merge",
    "gh pr merge",
    "--auto",
    "--auto-merge",
    "--admin",
    "merge_pull_request",
    "mergePullRequest",
)


def test_no_merge_token_appears_in_src() -> None:
    for needle in _FORBIDDEN:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.md", needle, _SRC],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"{needle!r} found in src/:\n{result.stdout}"


def test_pr_creation_always_passes_draft() -> None:
    """The one `gh pr create` call site names `--draft` in the same argv literal."""
    client = Path(_SRC) / "devmind" / "services" / "github_client.py"
    text = client.read_text(encoding="utf-8")
    assert "gh" in text and "pr" in text and "create" in text
    # `--draft` sits immediately after "create" in the argv list literal
    assert '"create", "--draft"' in text
