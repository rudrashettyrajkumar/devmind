"""Fixtures shared by the E4 ingestion service tests.

`seeded_git_repo` builds a real local git repository (no network) that the cloner and
the ingestion service clone from; `real_command_runner` is the production
`SubprocessCommandRunner` for the tests that must exercise actual `git`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from devmind.services.subprocess_command_runner import SubprocessCommandRunner


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def real_command_runner() -> SubprocessCommandRunner:
    return SubprocessCommandRunner(default_timeout=30)


@pytest.fixture
def seeded_git_repo(tmp_path: Path) -> Path:
    """A committed local repo with a `src/` package, a `tests/` dir, and a pyproject
    that declares pytest — the shape `RepoProfiler` and `SymbolIndexer` are asserted
    against.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "dev@example.test")
    _git(origin, "config", "user.name", "DevMind Test")

    _write(
        origin / "pyproject.toml",
        '[project]\nname = "sample"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
    )
    _write(origin / "src" / "sample" / "__init__.py", "")
    _write(
        origin / "src" / "sample" / "calc.py",
        "class Calculator:\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a - b\n\n\n"
        "def helper() -> int:\n"
        "    return 1\n",
    )
    _write(origin / "src" / "sample" / "__main__.py", "def main() -> None:\n    pass\n")
    _write(
        origin / "tests" / "test_calc.py",
        "from sample.calc import Calculator\n\n\n"
        "def test_add() -> None:\n"
        "    assert Calculator().add(2, 2) == 4\n",
    )
    _write(origin / "README.md", "# sample\n")
    _write(origin / ".gitignore", "*.log\nbuild/\n")

    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "initial commit")
    return origin


@pytest.fixture
def empty_git_repo(tmp_path: Path) -> Path:
    """An initialised repo with no commits — clones fine, has no HEAD."""
    origin = tmp_path / "empty-origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    return origin


@pytest.fixture
def tree_dir(tmp_path: Path) -> Iterator[Path]:
    """A plain directory tree (not a git repo) for tree/symbol/search tests."""
    root = tmp_path / "tree"
    layout: Sequence[tuple[str, str]] = (
        ("pkg/__init__.py", ""),
        ("pkg/core.py", "class Core:\n    pass\n\n\ndef run():\n    return 2\n"),
        ("pkg/sub/mod.py", "def deep():\n    return 3\n"),
        ("app.js", "export function widget() {}\nclass Thing {}\n"),
        ("notes.txt", "search me here\nand here too\n"),
        ("debug.log", "should be gitignored\n"),
        ("node_modules/dep/index.js", "function vendored() {}\n"),
        (".gitignore", "*.log\n"),
    )
    for rel, content in layout:
        _write(root / rel, content)
    yield root
