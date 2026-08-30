from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session as SQLAlchemySession

from devmind.core.enums import EventType, IssueState, TestFramework
from devmind.exceptions import GitHubError, RepositoryIngestionError
from devmind.models.session import SessionModel
from devmind.repositories import EventRepository, SessionRepository
from devmind.schemas.github import IssueRead
from devmind.schemas.session import SessionCreate
from devmind.services.code_index_service import CodeIndexService
from devmind.services.git_repository_cloner import GitRepositoryCloner
from devmind.services.github_client import GitHubClient
from devmind.services.repo_brief_builder import RepoBriefBuilder
from devmind.services.repo_ingestion_service import RepoIngestionService
from devmind.services.repo_profiler import RepoProfiler
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from devmind.services.symbol_indexer import SymbolIndexer
from devmind.services.workspace_manager import WorkspaceManager
from tests.fakes.fake_command_runner import FakeCommandRunner

_HUGE = 10 * 1024**3


class _StubGitHub(GitHubClient):
    """Direct mock of `GitHubClient` — the spec keeps it a plain class, mocked here
    rather than behind an ABC.
    """

    def __init__(self, *, issue: IssueRead | None = None, error: GitHubError | None = None) -> None:
        self._issue = issue
        self._error = error
        self.calls: list[tuple[str, int]] = []

    async def fetch_issue(self, repo_url: str, number: int) -> IssueRead:
        self.calls.append((repo_url, number))
        if self._error is not None:
            raise self._error
        assert self._issue is not None
        return self._issue


def _seed_session(
    sessions: SessionRepository,
    db_session: SQLAlchemySession,
    *,
    repo_url: str,
    issue_number: int | None = None,
    issue_description: str | None = None,
) -> SessionModel:
    """Create a session row, then point it at a local path.

    `SessionCreate` only accepts http(s)/SSH remotes (an E2 rule); the ingestion
    tests clone from a local fixture repo, so the row is created with a placeholder
    remote and its `repo_url` rewritten directly on the model.
    """
    created = sessions.create(
        SessionCreate(
            repo_url="https://github.com/example/placeholder",
            issue_number=issue_number,
            issue_description=issue_description,
        )
    )
    created.repo_url = repo_url
    db_session.commit()
    db_session.refresh(created)
    return created


def _build_service(
    *,
    workspace_root: Path,
    git_runner: SubprocessCommandRunner,
    github: GitHubClient,
    sessions: SessionRepository,
    events: EventRepository,
) -> RepoIngestionService:
    return RepoIngestionService(
        workspaces=WorkspaceManager(workspace_root, max_bytes=_HUGE),
        github=github,
        cloner=GitRepositoryCloner(git_runner),
        profiler=RepoProfiler(),
        code_index=CodeIndexService(),
        symbol_indexer=SymbolIndexer(),
        brief_builder=RepoBriefBuilder(),
        sessions=sessions,
        events=events,
    )


async def test_ingest_from_free_text_description(
    db_session: SQLAlchemySession,
    seeded_git_repo: Path,
    real_command_runner: SubprocessCommandRunner,
    tmp_path: Path,
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    session = _seed_session(
        sessions,
        db_session,
        repo_url=str(seeded_git_repo),
        issue_description="add() returns wrong value",
    )
    service = _build_service(
        workspace_root=tmp_path / "ws",
        git_runner=real_command_runner,
        github=GitHubClient(FakeCommandRunner(), token=None),
        sessions=sessions,
        events=events,
    )

    result = await service.ingest(session.id)

    assert Path(result.workspace_path).is_dir()
    assert result.base_commit_sha
    assert result.default_branch == "main"
    assert result.profile.test_framework is TestFramework.PYTEST
    assert result.profile.has_test_suite is True
    assert result.issue is None
    calc_modules = [m for m in result.symbol_index.modules if m.module.endswith("calc.py")]
    assert calc_modules and {s.name for s in calc_modules[0].symbols} >= {"Calculator", "add"}
    assert len(result.brief.render()) <= 8_000

    persisted = sessions.get_by_id(session.id)
    assert persisted is not None
    assert persisted.base_commit_sha == result.base_commit_sha
    assert persisted.workspace_path == result.workspace_path
    assert persisted.has_test_suite is True

    step_events = [
        e for e in events.list_since(session.id) if e.event_type is EventType.INGESTION_STEP
    ]
    steps = [e.payload["step"] for e in step_events]
    assert steps == ["workspace_created", "cloned", "issue_resolved", "profiled", "indexed"]


async def test_ingest_fetches_issue_when_number_given(
    db_session: SQLAlchemySession,
    seeded_git_repo: Path,
    real_command_runner: SubprocessCommandRunner,
    tmp_path: Path,
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    session = _seed_session(sessions, db_session, repo_url=str(seeded_git_repo), issue_number=5)

    github = _StubGitHub(
        issue=IssueRead(number=5, title="Broken add", body="add subtracts", state=IssueState.OPEN)
    )
    service = _build_service(
        workspace_root=tmp_path / "ws",
        git_runner=real_command_runner,
        github=github,
        sessions=sessions,
        events=events,
    )

    result = await service.ingest(session.id)

    assert result.issue is not None
    assert result.issue.title == "Broken add"
    persisted = sessions.get_by_id(session.id)
    assert persisted is not None
    assert persisted.issue_title == "Broken add"
    assert persisted.issue_body == "add subtracts"


async def test_clone_failure_becomes_ingestion_error_and_emits_session_failed(
    db_session: SQLAlchemySession,
    real_command_runner: SubprocessCommandRunner,
    tmp_path: Path,
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    session = _seed_session(
        sessions,
        db_session,
        repo_url=str(tmp_path / "no-such-repo"),
        issue_description="whatever",
    )
    service = _build_service(
        workspace_root=tmp_path / "ws",
        git_runner=real_command_runner,
        github=GitHubClient(FakeCommandRunner(), token=None),
        sessions=sessions,
        events=events,
    )

    with pytest.raises(RepositoryIngestionError):
        await service.ingest(session.id)

    failures = [
        e for e in events.list_since(session.id) if e.event_type is EventType.SESSION_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].payload["stage"] == "ingestion"


async def test_issue_fetch_failure_becomes_ingestion_error(
    db_session: SQLAlchemySession,
    seeded_git_repo: Path,
    real_command_runner: SubprocessCommandRunner,
    tmp_path: Path,
) -> None:
    sessions = SessionRepository(db_session)
    events = EventRepository(db_session)
    session = _seed_session(sessions, db_session, repo_url=str(seeded_git_repo), issue_number=404)
    github = _StubGitHub(error=GitHubError("issue #404 not found"))
    service = _build_service(
        workspace_root=tmp_path / "ws",
        git_runner=real_command_runner,
        github=github,
        sessions=sessions,
        events=events,
    )

    with pytest.raises(RepositoryIngestionError):
        await service.ingest(session.id)
