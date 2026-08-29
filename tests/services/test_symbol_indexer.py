from __future__ import annotations

from pathlib import Path

import pytest

from devmind.core.enums import SymbolKind
from devmind.schemas.repo import ModuleSymbols, SymbolIndex
from devmind.services.symbol_indexer import SymbolIndexer


@pytest.fixture
def indexer() -> SymbolIndexer:
    return SymbolIndexer()


def _module(index: SymbolIndex, name: str) -> ModuleSymbols:
    return next(m for m in index.modules if m.module == name)


def test_python_classes_and_functions_with_line_numbers(
    indexer: SymbolIndexer, tmp_path: Path
) -> None:
    (tmp_path / "mod.py").write_text(
        "import os\n\n\n"
        "class Alpha:\n"
        "    def method(self):\n"
        "        return 1\n\n\n"
        "def top_level():\n"
        "    return 2\n"
    )
    index = indexer.index(tmp_path)
    module = _module(index, "mod.py")
    by_name = {s.name: s for s in module.symbols}
    assert by_name["Alpha"].kind is SymbolKind.CLASS
    assert by_name["Alpha"].lineno == 4
    assert by_name["method"].kind is SymbolKind.FUNCTION
    assert by_name["method"].lineno == 5
    assert by_name["top_level"].lineno == 9


def test_async_functions_are_indexed(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("async def fetch():\n    return None\n")
    index = indexer.index(tmp_path)
    assert _module(index, "a.py").symbols[0].name == "fetch"


def test_broken_file_is_skipped_not_fatal(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def ok():\n    return 1\n")
    (tmp_path / "broken.py").write_text("def (this is not python\n")
    index = indexer.index(tmp_path)
    assert "broken.py" in index.skipped
    assert any(m.module == "good.py" for m in index.modules)


def test_non_python_regex_fallback(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "widget.js").write_text(
        "export function render() {}\nclass Widget {}\nconst x = 1;\n"
    )
    index = indexer.index(tmp_path)
    module = _module(index, "widget.js")
    kinds = {s.name: s.kind for s in module.symbols}
    assert kinds["render"] is SymbolKind.FUNCTION
    assert kinds["Widget"] is SymbolKind.CLASS


def test_ignored_directories_are_not_walked(indexer: SymbolIndexer, tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "junk.py").write_text("def junk():\n    pass\n")
    (tmp_path / "real.py").write_text("def real():\n    pass\n")
    index = indexer.index(tmp_path)
    assert [m.module for m in index.modules] == ["real.py"]


def test_files_without_symbols_are_omitted(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\ny = 2\n")
    index = indexer.index(tmp_path)
    assert index.modules == ()


def test_non_utf8_python_file_is_skipped_not_fatal(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "latin.py").write_bytes(b"def caf\xe9():\n    pass\n")
    (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
    index = indexer.index(tmp_path)
    assert "latin.py" in index.skipped
    assert [m.module for m in index.modules] == ["ok.py"]


def test_non_utf8_non_python_file_is_skipped(indexer: SymbolIndexer, tmp_path: Path) -> None:
    (tmp_path / "weird.js").write_bytes(b"function f\xff() {}\n")
    index = indexer.index(tmp_path)
    assert "weird.js" in index.skipped
