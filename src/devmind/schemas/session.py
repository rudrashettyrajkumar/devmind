"""Request/response DTOs for the session aggregate."""

import re
from datetime import datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from devmind.core.enums import SandboxBackend, SessionStatus

# A plain `HttpUrl` type would reject the SSH-style `git@host:owner/repo.git` shape a
# real coding agent is routinely pointed at, so `repo_url` stays `str` with this
# permissive shape check instead of a stricter URL type.
_REPO_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(https?://|git@)\S+$")


class SessionCreate(BaseModel):
    """The user's request to start a session: `{repo_url, issue_number_or_description}`."""

    repo_url: str = Field(min_length=1)
    issue_number: int | None = Field(default=None, gt=0)
    issue_description: str | None = Field(default=None, min_length=1)

    @field_validator("repo_url")
    @classmethod
    def _validate_repo_url_shape(cls, value: str) -> str:
        if not _REPO_URL_PATTERN.match(value):
            raise ValueError(
                "repo_url must be an http(s) URL or an SSH git remote (git@host:owner/repo.git)"
            )
        return value

    @model_validator(mode="after")
    def _exactly_one_issue_input(self) -> "SessionCreate":
        provided = [self.issue_number is not None, self.issue_description is not None]
        if sum(provided) != 1:
            raise ValueError("exactly one of issue_number or issue_description is required")
        return self


class SessionRead(BaseModel):
    """The full session state, as returned by `GET /sessions/{id}` (E11)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    issue_number: int | None
    issue_title: str | None
    issue_body: str | None
    base_commit_sha: str | None
    default_branch: str | None
    workspace_path: str | None
    branch_name: str | None
    status: SessionStatus
    sandbox_backend: SandboxBackend | None
    fix_attempts: int
    total_steps: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: float
    has_test_suite: bool
    failure_reason: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SessionSummary(BaseModel):
    """The lightweight view used for `GET /sessions` list results (E11)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    issue_number: int | None
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
