"""`BranchNamer` — the one place a delivery branch name is built (E10-F1-T2).

`devmind/issue-42-fix-timezone-parsing`, or `devmind/fix-timezone-parsing` when the
session was started from free text with no issue number. The slug is lowercase
ASCII, hyphen-separated, capped at `BRANCH_SLUG_MAX_CHARS`, with no leading or
trailing hyphen. A name already taken on the remote gets a `-2`, `-3`, … suffix.

A plain class — one implementation, pure string work, no I/O (Claude.md §9). The
caller passes the set of branch names already in use; this class never talks to git.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Final

from devmind.core.constants import (
    BRANCH_COLLISION_MAX_SUFFIX,
    BRANCH_PREFIX,
    BRANCH_SLUG_MAX_CHARS,
)
from devmind.exceptions import GitDeliveryError

_NON_SLUG_CHARS: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG: Final[str] = "change"


class BranchNamer:
    """Builds a collision-free `devmind/…` branch name from an issue and a title."""

    def build(
        self,
        issue_number: int | None,
        title: str,
        *,
        taken: Collection[str] = (),
    ) -> str:
        """Return the branch name to create.

        `taken` is the collection of names that must not be reused (typically the
        remote's existing branches). Raises `GitDeliveryError` only in the
        pathological case where every suffix up to `BRANCH_COLLISION_MAX_SUFFIX` is
        also taken.
        """
        slug = self._slugify(title)
        stem = f"issue-{issue_number}-{slug}" if issue_number is not None else slug
        base = f"{BRANCH_PREFIX}/{stem}".rstrip("-")

        taken_set = set(taken)
        if base not in taken_set:
            return base
        for suffix in range(2, BRANCH_COLLISION_MAX_SUFFIX + 1):
            candidate = f"{base}-{suffix}"
            if candidate not in taken_set:
                return candidate
        raise GitDeliveryError(
            f"could not find a free branch name for {base!r} after "
            f"{BRANCH_COLLISION_MAX_SUFFIX} attempts",
            details={"base": base},
        )

    @staticmethod
    def _slugify(title: str) -> str:
        slug = _NON_SLUG_CHARS.sub("-", title.strip().lower()).strip("-")
        if len(slug) > BRANCH_SLUG_MAX_CHARS:
            slug = slug[:BRANCH_SLUG_MAX_CHARS].rstrip("-")
        return slug or _FALLBACK_SLUG
