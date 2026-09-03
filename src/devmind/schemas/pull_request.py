"""DTOs for the write phase — the one draft PR a session ever opens (E10).

`CommitMessage` renders the conventional-commit text including the permanent
`Approved-by` / `Co-Authored-By` trailers; `DraftPullRequest` is what
`GitHubClient.create_draft_pr()` returns; `PullRequestRead` is the projection of the
persisted `PullRequestModel` that `PRService.open_draft_pr()` hands back.

Read-only after creation: nothing in this codebase updates or merges a PR (SI-6).
"""

from __future__ import annotations

import textwrap
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.constants import COMMIT_BODY_WRAP_COLUMNS, COMMIT_COAUTHOR_TRAILER


class CommitMessage(BaseModel):
    """The commit `PRService` asks `GitService` to create.

    `.render()` is the single source of the on-disk message: a conventional-commit
    subject, the agent's change summary hard-wrapped at 72 columns, then the trailer
    block. The `Refs:` line is present only when the session is tied to an issue
    number; `Approved-by` is always present — a commit DevMind makes always names the
    human who approved it.
    """

    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1)
    body: str = ""
    issue_number: int | None = None
    session_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)

    def render(self) -> str:
        """The full commit message text, trailers included."""
        blocks: list[str] = [self.subject.strip()]

        wrapped = self._wrapped_body()
        if wrapped:
            blocks.append(wrapped)

        trailers = [f"Session: {self.session_id}", f"Approved-by: {self.approved_by}"]
        if self.issue_number is not None:
            trailers.insert(0, f"Refs: #{self.issue_number}")
        trailers.append(COMMIT_COAUTHOR_TRAILER)
        blocks.append("\n".join(trailers))

        return "\n\n".join(blocks) + "\n"

    def _wrapped_body(self) -> str:
        paragraphs = [p.strip() for p in self.body.strip().split("\n\n") if p.strip()]
        wrapped = [
            textwrap.fill(
                " ".join(paragraph.split()),
                width=COMMIT_BODY_WRAP_COLUMNS,
                break_long_words=False,
                break_on_hyphens=False,
            )
            for paragraph in paragraphs
        ]
        return "\n\n".join(wrapped)


class DraftPullRequest(BaseModel):
    """What `gh pr create --draft` yields: the new PR's number and URL."""

    model_config = ConfigDict(frozen=True)

    number: int
    url: str


class PullRequestRead(BaseModel):
    """One session's delivered draft PR, as `PRService.open_draft_pr()` returns it.

    `dry_run` is `True` only for the synthetic result produced when `settings.dry_run`
    is set — no branch was pushed, no PR exists, and nothing was persisted.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    number: int
    url: str
    branch: str
    head_sha: str
    created_at: datetime
    dry_run: bool = False
