"""`GitHubClient` — a thin wrapper over the `gh` CLI, reads only (E4, design §10).

`gh issue view <n> --repo <slug> --json ...` and nothing else. No branch, no push,
no PR — that code does not exist until E10, which is gated on E9. One implementation,
mocked in tests through the injected `CommandRunner`; no ABC (Claude.md §9).
"""

from __future__ import annotations

import json
import re
from typing import Final

from devmind.core.constants import GH_ISSUE_TIMEOUT_SECONDS, GITHUB_ISSUE_JSON_FIELDS
from devmind.core.enums import IssueState
from devmind.exceptions import GitHubError
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput
from devmind.schemas.github import IssueRead

_SLUG_FROM_HTTPS: Final[re.Pattern[str]] = re.compile(
    r"^https?://[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_SLUG_FROM_SSH: Final[re.Pattern[str]] = re.compile(
    r"^git@[^:]+:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


class GitHubClient:
    """Fetches issue metadata for the ingestion phase."""

    def __init__(self, runner: CommandRunner, token: str | None) -> None:
        self._runner = runner
        self._token = token

    async def fetch_issue(self, repo_url: str, number: int) -> IssueRead:
        """Return the issue as `gh` reports it.

        Raises `GitHubError` if the slug can't be derived, `gh` exits non-zero (issue
        not found, no auth, unknown repo), or the JSON does not parse.
        """
        slug = self._repo_slug(repo_url)
        argv = [
            "gh",
            "issue",
            "view",
            str(number),
            "--repo",
            slug,
            "--json",
            GITHUB_ISSUE_JSON_FIELDS,
        ]
        env = {"GH_TOKEN": self._token} if self._token else None
        result = await self._runner.run(argv, env=env, timeout=GH_ISSUE_TIMEOUT_SECONDS)
        if not result.ok:
            raise self._error("gh issue view failed", slug, number, result)
        return self._parse(result.stdout, slug, number)

    @staticmethod
    def _repo_slug(repo_url: str) -> str:
        for pattern in (_SLUG_FROM_HTTPS, _SLUG_FROM_SSH):
            match = pattern.match(repo_url.strip())
            if match:
                return f"{match.group('owner')}/{match.group('repo')}"
        raise GitHubError(
            f"cannot derive an owner/repo slug from {repo_url!r}",
            details={"repo_url": repo_url},
        )

    def _parse(self, stdout: str, slug: str, number: int) -> IssueRead:
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(
                f"gh issue view returned unparseable JSON for {slug}#{number}",
                details={"slug": slug, "number": number},
            ) from exc
        if not isinstance(raw, dict):
            raise GitHubError(
                f"gh issue view returned a non-object for {slug}#{number}",
                details={"slug": slug, "number": number},
            )

        labels_raw = raw.get("labels") or []
        labels = tuple(
            label["name"]
            for label in labels_raw
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        )
        try:
            state = IssueState(str(raw.get("state", "")).lower())
        except ValueError:
            state = IssueState.OPEN

        return IssueRead(
            number=int(raw.get("number", number)),
            title=str(raw.get("title") or ""),
            body=str(raw.get("body") or ""),
            labels=labels,
            state=state,
        )

    @staticmethod
    def _error(prefix: str, slug: str, number: int, result: CommandOutput) -> GitHubError:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
        return GitHubError(
            f"{prefix} for {slug}#{number}: {detail}",
            details={
                "slug": slug,
                "number": number,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            },
        )
