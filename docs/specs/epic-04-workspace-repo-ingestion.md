# Spec — E4: Workspace & Repository Ingestion

| | |
|---|---|
| **Epic** | E4 |
| **Depends on** | E1, E2 |
| **Blocks** | E5, E6 |
| **Size** | M (~1.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

Turn `{repo_url, issue}` into an isolated workspace on disk plus enough structural knowledge for
an agent to navigate the code without reading all of it. Also home to `WorkspacePathGuard`, the
single mechanism enforcing safety invariant **SI-5**.

## Design references

`docs/01-solution-design.md` §3 (SI-5), §10 (read-phase GitHub), §16 (ingestion failure modes).

## Contracts

### `WorkspacePathGuard` — SI-5

The most security-relevant class in the codebase. Every path-taking tool goes through it.

```python
class WorkspacePathGuard:
    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root.resolve(strict=True)

    def resolve(self, candidate: str | Path) -> Path:
        """Resolve `candidate` inside the workspace.

        Raises PathEscapeError if the resolved path is outside the root, including
        via `..`, an absolute path, or a symlink pointing out.
        """
        target = (self._root / candidate).resolve()
        if not target.is_relative_to(self._root):
            raise PathEscapeError(...)
        return target
```

`Path.resolve()` follows symlinks, so the check catches a symlink escape as well as `../`. Do
not "optimise" it into string prefix matching — `/workspace-evil` starts with `/workspace`.

### `WorkspaceManager`

```python
class WorkspaceManager:
    def __init__(self, root: Path, max_bytes: int) -> None: ...
    def create(self, session_id: str) -> Path: ...
    def guard_for(self, session_id: str) -> WorkspacePathGuard: ...
    def destroy(self, session_id: str) -> None: ...
    def usage_bytes(self) -> int: ...
```

Refuse to create a workspace when the root is over its disk ceiling — a disk-full failure at
minute nine of a run is a bad way to find out.

### `RepoIngestionService`

```python
class RepoIngestionService:
    def __init__(self, workspaces: WorkspaceManager, github: GitHubClient,
                 sessions: SessionRepository, events: EventRepository) -> None: ...

    async def ingest(self, session_id: str) -> IngestionResult: ...
```

Steps, each emitting an event:

1. Create the workspace.
2. `git clone --depth 50 <url> <path>` — depth 50, not 1: `git diff` and blame-style
   investigation need a little history, and a full clone of a large repo is minutes wasted.
3. Record `base_commit_sha` (`git rev-parse HEAD`) and the default branch.
4. Fetch the issue (below), or accept the free-text description.
5. Profile the repo.
6. Build the tree, the symbol index, and the `RepoBrief`.

Failure modes map to `RepositoryIngestionError` with an actionable message: unreachable URL,
private repo without credentials, issue not found, empty repo, no default branch.

### `GitHubClient` — plain class, no ABC

```python
class GitHubClient:
    def __init__(self, runner: CommandRunner, token: str | None) -> None: ...
    async def fetch_issue(self, repo_url: str, number: int) -> IssueRead: ...
```

`gh issue view <n> --repo <repo> --json number,title,body,labels,state`. Parse into `IssueRead`.
One implementation; mocked directly in tests. `Claude.md` §9 — no ABC.

> **Scope boundary:** this epic uses `gh` for **reads only**. Nothing here creates a branch,
> pushes, or opens a PR. That code does not exist until E10, and E10 is gated on E9.

### `RepoProfile`

```python
class RepoProfile(BaseModel):
    language: str
    test_framework: str | None          # "pytest" | None
    test_paths: list[str]
    dependency_manager: str | None      # "uv" | "poetry" | "pip" | None
    install_command: list[str] | None
    test_command: list[str]
    package_dirs: list[str]
    has_test_suite: bool
```

Detection is evidence-based, in priority order: `pyproject.toml` (`[tool.pytest.ini_options]`,
`[project.optional-dependencies]`), `pytest.ini`/`tox.ini`/`setup.cfg`, then a `tests/`
directory, then `test_*.py` anywhere. `has_test_suite=False` is a legitimate outcome and must
propagate to the session record — E8 and E9 both change behaviour on it.

### `CodeIndexService` and `SymbolIndexer`

```python
class CodeIndexService:
    def build_tree(self, root: Path, *, max_depth: int, max_entries: int) -> FileTree: ...

class SymbolIndexer:
    def index(self, root: Path) -> SymbolIndex: ...   # module -> classes/functions with line numbers
```

Python via `ast` (never `exec`, never import the target code — indexing an untrusted repo must
not run it). Non-Python files get a regex fallback for `class`/`def`/`function`. A file that
fails to parse is skipped with a debug log, never fatal — half-broken repos are normal.

Both respect `.gitignore` and skip `.git`, `node_modules`, `.venv`, `__pycache__`, and binaries.

### `RepoBrief`

The cacheable structural summary injected into the system prefix (E3-F2-T1). Hard token budget
— roughly 2,000 tokens — containing: repo name, language, test framework and command, top-level
tree to depth 2, the largest/most-central modules, and the entry points. Deterministic output
for a given commit, because it sits inside the cached prefix and any variation invalidates it.

### `CodeSearchService`

```python
class CodeSearchService:
    async def search(self, root: Path, pattern: str, *, glob: str | None,
                     max_results: int) -> list[SearchHit]: ...
```

`rg --json` when ripgrep exists, `grep -rn` otherwise. Structured `SearchHit(path, line,
text)`; results capped and each line truncated so one unlucky minified file can't blow the
context window.

## Task plan

E4-F1-T1 … E4-F3-T4. Path guard first — everything else depends on it and it is the one piece
that must be right.

## Testing

| Test | Proves |
|---|---|
| `test_path_guard.py` | `../../etc/passwd`, `/etc/passwd`, `a/../../..`, a symlink to `/tmp`, and a symlinked directory all raise; legitimate nested paths resolve |
| `test_workspace_manager.py` | Create/destroy; disk ceiling refuses |
| `test_repo_ingestion.py` | Against a locally-created git repo fixture: clone, SHA recorded, profile built |
| `test_repo_profile.py` | pytest detected from `pyproject.toml`, from `pytest.ini`, from a bare `tests/` dir; `has_test_suite=False` when there is none |
| `test_symbol_indexer.py` | Classes and functions with line numbers; a syntactically broken file is skipped, not fatal |
| `test_repo_brief.py` | Deterministic for a fixed commit; stays under the token budget |
| `test_github_client.py` | Mocked `gh` returns parsed `IssueRead`; a missing issue raises `GitHubError` |

The path-guard tests are the highest-value tests in this epic. Write them adversarially.

## Acceptance criteria

- [ ] Ingesting a real public repo yields workspace + profile + symbol index + brief.
- [ ] `WorkspacePathGuard` rejects every escape vector in the test list.
- [ ] `has_test_suite=False` is detected and recorded on the session.
- [ ] `RepoBrief` is deterministic and within budget.
- [ ] No push/PR code exists anywhere in this epic.
- [ ] `make check` green.

## Notes

- **No vector index.** Design §2 records the decision: ripgrep plus a symbol map answers "where
  is X" at this scope. Do not add embeddings.
- Never import or execute the target repository's code. Static analysis only — DevMind indexes
  code it does not trust.
- Clone with `GIT_TERMINAL_PROMPT=0` and `GIT_ASKPASS=/bin/false` so a private repo fails fast
  instead of hanging on a credential prompt.
