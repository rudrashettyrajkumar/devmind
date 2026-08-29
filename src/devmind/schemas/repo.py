"""DTOs for repository ingestion and the code index (E4).

Everything an agent needs to navigate a repo without reading all of it: a profile of
how it is built and tested, a depth-capped file tree, an AST-derived symbol map, and
the compact `RepoBrief` that sits in the cached system prefix.

No vector index — ripgrep plus this symbol map answers "where is X" at this scope
(docs/01-solution-design.md §2). Nothing here imports or executes the target repo.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from devmind.core.constants import (
    REPO_BRIEF_MAX_CHARS,
    REPO_BRIEF_MAX_ENTRY_POINTS,
    REPO_BRIEF_MAX_KEY_MODULES,
    REPO_BRIEF_MAX_TREE_LINES,
)
from devmind.core.enums import DependencyManager, SymbolKind, TestFramework
from devmind.schemas.github import IssueRead


class FileTreeNode(BaseModel):
    """One node in the repo file tree. `children` is always empty for a file and for
    a directory pruned at the depth or entry cap.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    is_dir: bool
    children: tuple[FileTreeNode, ...] = ()


class FileTree(BaseModel):
    """A gitignore-aware, depth- and count-capped view of the repo layout."""

    model_config = ConfigDict(frozen=True)

    root: FileTreeNode
    entry_count: int
    truncated: bool = False


class Symbol(BaseModel):
    """One class or function definition and the 1-based line it starts on."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: SymbolKind
    lineno: int


class ModuleSymbols(BaseModel):
    """Every top-level and nested definition found in one source file."""

    model_config = ConfigDict(frozen=True)

    module: str
    symbols: tuple[Symbol, ...] = ()


class SymbolIndex(BaseModel):
    """The whole-repo symbol map. `skipped` lists files that failed to parse — a
    half-broken repo is normal and never fatal to indexing.
    """

    model_config = ConfigDict(frozen=True)

    modules: tuple[ModuleSymbols, ...] = ()
    skipped: tuple[str, ...] = ()


class RepoProfile(BaseModel):
    """Evidence-based detection of how a repo is built and tested (spec §RepoProfile).

    `has_test_suite=False` is a legitimate outcome and propagates to the session
    record — E8 and E9 both change behaviour on it.
    """

    model_config = ConfigDict(frozen=True)

    language: str
    test_framework: TestFramework | None = None
    test_paths: tuple[str, ...] = ()
    dependency_manager: DependencyManager | None = None
    install_command: tuple[str, ...] | None = None
    test_command: tuple[str, ...] = ()
    package_dirs: tuple[str, ...] = ()
    has_test_suite: bool = False


class RepoBrief(BaseModel):
    """The cacheable structural summary injected into the system prefix (E3-F2-T1).

    Deterministic for a given commit: it sits inside the cached prefix and any
    variation invalidates everything after it. `render()` is a pure function of the
    fields — the `RepoBriefBuilder` is what keeps the fields within budget.
    """

    model_config = ConfigDict(frozen=True)

    repo_name: str
    language: str
    test_framework: TestFramework | None
    test_command: tuple[str, ...]
    tree_preview: str
    key_modules: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()

    def render(self) -> str:
        """The exact text block placed in the cached prefix. Pure and deterministic."""
        framework = (
            self.test_framework.value if self.test_framework is not None else "none detected"
        )
        command = " ".join(self.test_command) if self.test_command else "n/a"

        tree_lines = self.tree_preview.rstrip("\n").splitlines()[:REPO_BRIEF_MAX_TREE_LINES]
        modules = [f"- {module}" for module in self.key_modules[:REPO_BRIEF_MAX_KEY_MODULES]]
        entries = [f"- {entry}" for entry in self.entry_points[:REPO_BRIEF_MAX_ENTRY_POINTS]]

        lines: list[str] = [
            f"# Repository: {self.repo_name}",
            f"Language: {self.language}",
            f"Test framework: {framework}",
            f"Test command: {command}",
            "",
            "## Structure (depth 2)",
            *(tree_lines or ["(empty)"]),
            "",
            "## Key modules",
            *(modules or ["(none)"]),
            "",
            "## Entry points",
            *(entries or ["(none)"]),
        ]
        text = "\n".join(lines)
        if len(text) > REPO_BRIEF_MAX_CHARS:
            marker = "\n[brief truncated to fit the token budget]"
            text = text[: REPO_BRIEF_MAX_CHARS - len(marker)] + marker
        return text


class SearchHit(BaseModel):
    """One ripgrep/grep match: file, 1-based line, and the (truncated) line text."""

    model_config = ConfigDict(frozen=True)

    path: str
    line: int
    text: str


class IngestionResult(BaseModel):
    """Everything `RepoIngestionService.ingest()` produces for one session."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    workspace_path: str
    base_commit_sha: str
    default_branch: str
    profile: RepoProfile
    brief: RepoBrief
    symbol_index: SymbolIndex
    file_tree: FileTree
    issue: IssueRead | None = None


# `FileTreeNode` refers to itself; resolve the forward reference now that the class
# body is complete.
FileTreeNode.model_rebuild()
