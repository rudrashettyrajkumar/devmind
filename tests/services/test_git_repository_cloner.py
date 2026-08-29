from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devmind.exceptions import RepositoryIngestionError
from devmind.services.git_repository_cloner import GitRepositoryCloner
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output


@pytest.fixture
def cloner(real_command_runner: SubprocessCommandRunner) -> GitRepositoryCloner:
    return GitRepositoryCloner(real_command_runner)


# --- failure classification (driven through the fake runner) ------------------


@pytest.mark.parametrize(
    ("stderr", "timed_out", "expected_fragment"),
    [
        ("fatal: repository 'https://x/y' not found", False, "was not found"),
        (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            False,
            "private and no credentials",
        ),
        ("fatal: Authentication failed for 'https://github.com/x/y'", False, "private"),
        ("fatal: unable to access 'https://x/y': Could not resolve host: x", False, "unreachable"),
        ("", True, "timed out"),
        ("fatal: something else entirely broke", False, "failed"),
    ],
)
async def test_clone_failure_is_classified(
    stderr: str, timed_out: bool, expected_fragment: str, tmp_path: Path
) -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("git", "clone"): command_output(
                ["git", "clone"], exit_code=128, stderr=stderr, timed_out=timed_out
            )
        }
    )
    cloner = GitRepositoryCloner(runner)
    with pytest.raises(RepositoryIngestionError) as excinfo:
        await cloner.clone("https://x/y", tmp_path / "dest")
    assert expected_fragment in str(excinfo.value)


async def test_default_branch_falls_back_to_current_branch(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        by_prefix={
            ("git", "symbolic-ref"): command_output(
                ["git", "symbolic-ref"], exit_code=128, stderr="not a symbolic ref"
            ),
            ("git", "rev-parse", "--abbrev-ref"): command_output(
                ["git", "rev-parse"], stdout="develop\n"
            ),
        }
    )
    assert await GitRepositoryCloner(runner).default_branch(tmp_path) == "develop"


async def test_default_branch_raises_when_nothing_resolves(tmp_path: Path) -> None:
    runner = FakeCommandRunner(default=command_output(["git"], exit_code=128, stderr="fatal: bad"))
    with pytest.raises(RepositoryIngestionError):
        await GitRepositoryCloner(runner).default_branch(tmp_path)


async def test_base_commit_sha_strips_whitespace(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        by_prefix={("git", "rev-parse", "HEAD"): command_output(["git"], stdout="  abc123\n  ")}
    )
    assert await GitRepositoryCloner(runner).base_commit_sha(tmp_path) == "abc123"


async def test_clone_populates_dest_and_reads_revision(
    cloner: GitRepositoryCloner, seeded_git_repo: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "clone"
    await cloner.clone(str(seeded_git_repo), dest)

    assert (dest / "pyproject.toml").is_file()
    assert (dest / "src" / "sample" / "calc.py").is_file()

    sha = await cloner.base_commit_sha(dest)
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=seeded_git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert sha == expected

    assert await cloner.default_branch(dest) == "main"


async def test_clone_of_a_bad_url_raises_repository_ingestion_error(
    cloner: GitRepositoryCloner, tmp_path: Path
) -> None:
    with pytest.raises(RepositoryIngestionError):
        await cloner.clone(str(tmp_path / "nope" / "not-a-repo"), tmp_path / "dest")


async def test_empty_repo_has_no_base_commit(
    cloner: GitRepositoryCloner, empty_git_repo: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "empty-clone"
    await cloner.clone(str(empty_git_repo), dest)
    with pytest.raises(RepositoryIngestionError) as excinfo:
        await cloner.base_commit_sha(dest)
    assert "empty" in str(excinfo.value).lower()
