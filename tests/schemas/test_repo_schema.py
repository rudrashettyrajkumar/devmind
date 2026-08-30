from __future__ import annotations

from devmind.core.enums import SymbolKind
from devmind.schemas.repo import (
    FileTree,
    FileTreeNode,
    ModuleSymbols,
    RepoBrief,
    Symbol,
    SymbolIndex,
)


def test_file_tree_node_is_recursive() -> None:
    node = FileTreeNode(
        name="root",
        is_dir=True,
        children=(
            FileTreeNode(
                name="pkg",
                is_dir=True,
                children=(FileTreeNode(name="mod.py", is_dir=False),),
            ),
        ),
    )
    tree = FileTree(root=node, entry_count=2)
    assert tree.root.children[0].children[0].name == "mod.py"


def test_symbol_index_defaults_are_empty() -> None:
    index = SymbolIndex()
    assert index.modules == ()
    assert index.skipped == ()


def test_repo_brief_render_is_pure_and_repeatable() -> None:
    brief = RepoBrief(
        repo_name="demo",
        language="python",
        test_framework="pytest",
        test_command=("python", "-m", "pytest"),
        tree_preview="src/\n  a.py\nREADME.md",
        key_modules=("src/a.py",),
        entry_points=("src/__main__.py",),
    )
    first = brief.render()
    assert first == brief.render()
    assert first.startswith("# Repository: demo")
    assert "python -m pytest" in first
    assert "- src/a.py" in first


def test_repo_brief_render_truncates_to_the_token_budget() -> None:
    from devmind.core.constants import REPO_BRIEF_MAX_CHARS

    brief = RepoBrief(
        repo_name="huge",
        language="python",
        test_framework=None,
        test_command=(),
        tree_preview="x" * (REPO_BRIEF_MAX_CHARS * 2),
    )
    rendered = brief.render()
    assert len(rendered) <= REPO_BRIEF_MAX_CHARS
    assert rendered.endswith("[brief truncated to fit the token budget]")


def test_repo_brief_render_handles_empty_sections() -> None:
    brief = RepoBrief(
        repo_name="bare",
        language="unknown",
        test_framework=None,
        test_command=(),
        tree_preview="",
    )
    rendered = brief.render()
    assert "Test framework: none detected" in rendered
    assert "Test command: n/a" in rendered
    assert "(none)" in rendered
    assert "(empty)" in rendered


def test_module_symbols_carry_kinds() -> None:
    module = ModuleSymbols(
        module="a.py",
        symbols=(Symbol(name="C", kind=SymbolKind.CLASS, lineno=1),),
    )
    assert module.symbols[0].kind is SymbolKind.CLASS
