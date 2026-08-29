"""`SymbolIndexer` — a module → class/function map with line numbers (E4-F3-T2).

Python files are parsed with `ast` — never `exec`, never imported. DevMind indexes
code it does not trust. Other known source suffixes get a regex fallback for
`class` / `def` / `function`. A file that fails to parse is added to `skipped` with a
debug log and the walk continues — half-broken repos are normal.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Final

from devmind.core.constants import BINARY_FILE_EXTENSIONS, REGEX_SYMBOL_EXTENSIONS
from devmind.core.enums import SymbolKind
from devmind.schemas.repo import ModuleSymbols, Symbol, SymbolIndex
from devmind.services.gitignore_filter import GitignoreFilter

logger = logging.getLogger(__name__)

_REGEX_SYMBOL: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:public\s+|private\s+|protected\s+|static\s+|"
    r"async\s+|final\s+|abstract\s+)*(?P<kw>class|def|function|func|interface|struct)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_CLASS_KEYWORDS: Final[frozenset[str]] = frozenset({"class", "interface", "struct"})


class SymbolIndexer:
    """Walks a repo and builds its whole-file symbol map."""

    def index(self, root: Path) -> SymbolIndex:
        gitignore = GitignoreFilter.for_root(root)
        modules: list[ModuleSymbols] = []
        skipped: list[str] = []

        for path in sorted(root.rglob("*"), key=lambda entry: entry.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if gitignore.ignores(rel, is_dir=False):
                continue

            suffix = path.suffix.lower()
            if suffix in BINARY_FILE_EXTENSIONS:
                continue

            if suffix == ".py":
                symbols = self._index_python(path)
            elif suffix in REGEX_SYMBOL_EXTENSIONS:
                symbols = self._index_regex(path)
            else:
                continue

            if symbols is None:
                skipped.append(rel.as_posix())
                continue
            if symbols:
                modules.append(ModuleSymbols(module=rel.as_posix(), symbols=tuple(symbols)))

        return SymbolIndex(modules=tuple(modules), skipped=tuple(skipped))

    @staticmethod
    def _index_python(path: Path) -> list[Symbol] | None:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("could not read %s: %s", path, exc)
            return None
        try:
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, ValueError) as exc:
            logger.debug("skipping unparseable python file %s: %s", path, exc)
            return None

        symbols: list[Symbol] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(Symbol(name=node.name, kind=SymbolKind.CLASS, lineno=node.lineno))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                symbols.append(Symbol(name=node.name, kind=SymbolKind.FUNCTION, lineno=node.lineno))
        symbols.sort(key=lambda symbol: (symbol.lineno, symbol.name))
        return symbols

    @staticmethod
    def _index_regex(path: Path) -> list[Symbol] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("could not read %s: %s", path, exc)
            return None

        symbols: list[Symbol] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _REGEX_SYMBOL.match(line)
            if match is None:
                continue
            kind = SymbolKind.CLASS if match.group("kw") in _CLASS_KEYWORDS else SymbolKind.FUNCTION
            symbols.append(Symbol(name=match.group("name"), kind=kind, lineno=lineno))
        return symbols
