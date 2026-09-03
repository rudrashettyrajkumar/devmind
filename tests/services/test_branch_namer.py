"""`BranchNamer` — slugging, the length cap, and collision suffixing (E10-F1-T2)."""

from __future__ import annotations

import pytest

from devmind.core.constants import BRANCH_SLUG_MAX_CHARS
from devmind.exceptions import GitDeliveryError
from devmind.services.branch_namer import BranchNamer


@pytest.fixture
def namer() -> BranchNamer:
    return BranchNamer()


def test_issue_branch_has_the_devmind_issue_prefix(namer: BranchNamer) -> None:
    assert namer.build(42, "Fix timezone parsing") == "devmind/issue-42-fix-timezone-parsing"


def test_slug_is_lowercase_ascii_hyphenated(namer: BranchNamer) -> None:
    name = namer.build(7, "  Handle Naïve DateTimes in parse_timestamp()!!  ")
    slug = name.removeprefix("devmind/issue-7-")
    assert slug == slug.lower()
    assert all(c.isalnum() or c == "-" for c in slug)
    assert "--" not in slug
    assert not slug.startswith("-") and not slug.endswith("-")


def test_slug_is_capped_and_has_no_trailing_hyphen(namer: BranchNamer) -> None:
    title = "a " * 60  # far past the cap, and would end on a hyphen if not trimmed
    name = namer.build(1, title)
    slug = name.removeprefix("devmind/issue-1-")
    assert len(slug) <= BRANCH_SLUG_MAX_CHARS
    assert not slug.endswith("-")


def test_no_issue_number_drops_the_issue_segment(namer: BranchNamer) -> None:
    assert namer.build(None, "Fix timezone parsing") == "devmind/fix-timezone-parsing"


def test_empty_title_falls_back_to_a_placeholder_slug(namer: BranchNamer) -> None:
    assert namer.build(9, "!!!") == "devmind/issue-9-change"


def test_collision_appends_a_numeric_suffix(namer: BranchNamer) -> None:
    taken = {"devmind/issue-42-fix-timezone-parsing"}
    assert (
        namer.build(42, "Fix timezone parsing", taken=taken)
        == "devmind/issue-42-fix-timezone-parsing-2"
    )


def test_collision_walks_past_multiple_taken_suffixes(namer: BranchNamer) -> None:
    base = "devmind/issue-42-fix-timezone-parsing"
    taken = {base, f"{base}-2", f"{base}-3"}
    assert namer.build(42, "Fix timezone parsing", taken=taken) == f"{base}-4"


def test_exhausting_every_suffix_raises(namer: BranchNamer) -> None:
    base = "devmind/issue-1-x"
    taken = {base} | {f"{base}-{n}" for n in range(2, 200)}
    with pytest.raises(GitDeliveryError):
        namer.build(1, "x", taken=taken)
