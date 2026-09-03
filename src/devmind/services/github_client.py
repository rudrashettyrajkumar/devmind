"""`GitHubClient` — a thin wrapper over the `gh` CLI (E4 read side, E10 write side).

Read phase (pre-approval): `gh issue view <n> --repo <slug> --json …`.
Write phase (post-approval only): `gh pr create --draft …`, called from `PRService`
after `RemoteOperationGuard.authorize()`. DevMind opens the draft and stops there —
it does not merge, enable auto-merge, edit, or close a pull request; that code does
not exist (SI-6). One implementation, mocked in tests through the injected
`CommandRunner`; no ABC (Claude.md §9).
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Final

from devmind.core.constants import (
    GH_ISSUE_TIMEOUT_SECONDS,
    GH_PR_CREATE_TIMEOUT_SECONDS,
    GITHUB_ISSUE_JSON_FIELDS,
)
from devmind.core.enums import GitFailureReason, IssueState
from devmind.exceptions import GitDeliveryError, GitHubError
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput
from devmind.schemas.github import IssueRead
from devmind.schemas.pull_request import DraftPullRequest

logger = logging.getLogger(__name__)

_PR_URL_NUMBER: Final[re.Pattern[str]] = re.compile(r"/pull/(?P<number>\d+)")

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

    async def create_draft_pr(
        self,
        repo_url: str,
        *,
        base: str,
        head: str,
        title: str,
        body: str,
        dry_run: bool = False,
    ) -> DraftPullRequest:
        """`gh pr create --draft --base <base> --head <head> …`.

        Always `--draft`. The body is passed via `--body-file` (a temp file, removed
        straight after) so an arbitrarily long body never rides on argv. Raises
        `GitDeliveryError` (reason `PR_CREATE_FAILED`) if `gh` exits non-zero — by
        then the branch is already pushed, so the caller records that for the human.
        """
        slug = self._repo_slug(repo_url)
        if dry_run:
            argv = [
                "gh", "pr", "create", "--draft",
                "--repo", slug, "--base", base, "--head", head,
                "--title", title, "--body-file", "<pr body>",
            ]  # fmt: skip
            logger.info("dry-run: would run %s", argv)
            return DraftPullRequest(number=0, url=f"https://github.com/{slug}/pull/DRY-RUN")

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", prefix="devmind-pr-body-", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
            body_file = Path(handle.name)
        try:
            argv = [
                "gh", "pr", "create", "--draft",
                "--repo", slug, "--base", base, "--head", head,
                "--title", title, "--body-file", str(body_file),
            ]  # fmt: skip
            env = {"GH_TOKEN": self._token} if self._token else None
            result = await self._runner.run(argv, env=env, timeout=GH_PR_CREATE_TIMEOUT_SECONDS)
        finally:
            body_file.unlink(missing_ok=True)

        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            raise GitDeliveryError(
                f"gh pr create failed for {slug} (branch {head!r} was pushed and is "
                f"retained): {detail}",
                reason=GitFailureReason.PR_CREATE_FAILED,
                details={"slug": slug, "head": head, "exit_code": result.exit_code},
            )
        return self._parse_pr(result.stdout, slug)

    @staticmethod
    def _parse_pr(stdout: str, slug: str) -> DraftPullRequest:
        url = ""
        for line in stdout.splitlines():
            candidate = line.strip()
            if candidate.startswith("http") and "/pull/" in candidate:
                url = candidate
                break
        match = _PR_URL_NUMBER.search(url)
        if not url or match is None:
            raise GitDeliveryError(
                f"gh pr create for {slug} returned no parseable PR URL: {stdout.strip()!r}",
                reason=GitFailureReason.PR_CREATE_FAILED,
                details={"slug": slug, "stdout": stdout.strip()},
            )
        return DraftPullRequest(number=int(match.group("number")), url=url)

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
