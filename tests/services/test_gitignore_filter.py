from __future__ import annotations

from pathlib import Path

from devmind.services.gitignore_filter import GitignoreFilter


def _filter(patterns: list[str]) -> GitignoreFilter:
    from devmind.core.constants import INDEX_IGNORE_DIRS

    return GitignoreFilter(patterns, INDEX_IGNORE_DIRS)


def test_always_skips_hardcoded_dirs() -> None:
    gi = _filter([])
    assert gi.ignores(Path("node_modules/foo/index.js"), is_dir=False)
    assert gi.ignores(Path("pkg/__pycache__/x.pyc"), is_dir=False)
    assert not gi.ignores(Path("pkg/core.py"), is_dir=False)


def test_basename_glob() -> None:
    gi = _filter(["*.log"])
    assert gi.ignores(Path("deep/nested/debug.log"), is_dir=False)
    assert not gi.ignores(Path("deep/nested/debug.txt"), is_dir=False)


def test_directory_only_pattern() -> None:
    gi = _filter(["generated/"])
    assert gi.ignores(Path("generated"), is_dir=True)
    assert not gi.ignores(Path("generated"), is_dir=False)


def test_anchored_pattern() -> None:
    gi = _filter(["/coverage-out"])
    assert gi.ignores(Path("coverage-out"), is_dir=True)
    assert not gi.ignores(Path("pkg/coverage-out"), is_dir=True)


def test_negation_reincludes() -> None:
    gi = _filter(["*.log", "!keep.log"])
    assert gi.ignores(Path("a/debug.log"), is_dir=False)
    assert not gi.ignores(Path("a/keep.log"), is_dir=False)


def test_for_root_reads_dot_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# a comment\n\n*.tmp\nsecret/\n")
    gi = GitignoreFilter.for_root(tmp_path)
    assert gi.ignores(Path("x.tmp"), is_dir=False)
    assert gi.ignores(Path("secret"), is_dir=True)
    assert not gi.ignores(Path("x.py"), is_dir=False)


def test_for_root_without_gitignore_still_skips_defaults(tmp_path: Path) -> None:
    gi = GitignoreFilter.for_root(tmp_path)
    assert gi.ignores(Path(".git/config"), is_dir=False)
