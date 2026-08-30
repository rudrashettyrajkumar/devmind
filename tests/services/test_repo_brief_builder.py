from __future__ import annotations

from pathlib import Path

import pytest

from devmind.core.constants import REPO_BRIEF_MAX_CHARS
from devmind.core.enums import SymbolKind, TestFramework
from devmind.schemas.repo import (
    FileTree,
    FileTreeNode,
    ModuleSymbols,
    RepoProfile,
    Symbol,
    SymbolIndex,
)
from devmind.services.repo_brief_builder import RepoBriefBuilder


@pytest.fixture
def builder() -> RepoBriefBuilder:
    return RepoBriefBuilder()


def _tree() -> FileTree:
    root = FileTreeNode(
        name="root",
        is_dir=True,
        children=(
            FileTreeNode(
                name="src",
                is_dir=True,
                children=(FileTreeNode(name="calc.py", is_dir=False),),
            ),
            FileTreeNode(name="README.md", is_dir=False),
        ),
    )
    return FileTree(root=root, entry_count=3, truncated=False)


def _profile() -> RepoProfile:
    return RepoProfile(
        language="python",
        test_framework=TestFramework.PYTEST,
        test_command=("python", "-m", "pytest"),
        package_dirs=("src/sample",),
        has_test_suite=True,
    )


def _symbols() -> SymbolIndex:
    return SymbolIndex(
        modules=(
            ModuleSymbols(
                module="src/sample/calc.py",
                symbols=(
                    Symbol(name="Calc", kind=SymbolKind.CLASS, lineno=1),
                    Symbol(name="add", kind=SymbolKind.FUNCTION, lineno=2),
                ),
            ),
            ModuleSymbols(
                module="src/sample/util.py",
                symbols=(Symbol(name="helper", kind=SymbolKind.FUNCTION, lineno=1),),
            ),
        )
    )


def test_build_is_deterministic_for_fixed_inputs(builder: RepoBriefBuilder, tmp_path: Path) -> None:
    def _build() -> object:
        return builder.build(
            repo_url="https://github.com/acme/sample.git",
            profile=_profile(),
            file_tree=_tree(),
            symbol_index=_symbols(),
            root=tmp_path,
        )

    first = _build()
    second = _build()
    assert first == second


def test_brief_carries_the_expected_fields(builder: RepoBriefBuilder, tmp_path: Path) -> None:
    brief = builder.build(
        repo_url="https://github.com/acme/sample.git",
        profile=_profile(),
        file_tree=_tree(),
        symbol_index=_symbols(),
        root=tmp_path,
    )
    assert brief.repo_name == "sample"
    assert brief.language == "python"
    assert brief.test_framework == "pytest"
    assert brief.key_modules[0] == "src/sample/calc.py"  # most symbols first
    rendered = brief.render()
    assert "# Repository: sample" in rendered
    assert "calc.py" in rendered


def test_entry_points_detected_from_disk(builder: RepoBriefBuilder, tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("")
    pkg = tmp_path / "src" / "sample"
    pkg.mkdir(parents=True)
    (pkg / "__main__.py").write_text("")
    brief = builder.build(
        repo_url="https://github.com/acme/sample",
        profile=_profile(),
        file_tree=_tree(),
        symbol_index=_symbols(),
        root=tmp_path,
    )
    assert "manage.py" in brief.entry_points
    assert "src/sample/__main__.py" in brief.entry_points


def test_render_stays_within_the_token_budget(builder: RepoBriefBuilder, tmp_path: Path) -> None:
    big_tree = FileTree(
        root=FileTreeNode(
            name="root",
            is_dir=True,
            children=tuple(
                FileTreeNode(name=f"module_{i:04d}.py", is_dir=False) for i in range(5000)
            ),
        ),
        entry_count=5000,
        truncated=True,
    )
    big_symbols = SymbolIndex(
        modules=tuple(
            ModuleSymbols(
                module=f"pkg/module_{i:04d}.py",
                symbols=(Symbol(name=f"fn_{i}", kind=SymbolKind.FUNCTION, lineno=1),),
            )
            for i in range(5000)
        )
    )
    brief = builder.build(
        repo_url="https://github.com/acme/huge",
        profile=_profile(),
        file_tree=big_tree,
        symbol_index=big_symbols,
        root=tmp_path,
    )
    assert len(brief.render()) <= REPO_BRIEF_MAX_CHARS
