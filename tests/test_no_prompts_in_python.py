"""Fails if prompt-shaped text appears as a string literal anywhere under `src/`.

Prompts live in `src/devmind/prompts/*.md` and nowhere else (Claude.md §8). The
heuristic: a non-docstring string literal that is both long and multi-paragraph is
almost certainly a prompt body that escaped into Python.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "devmind"
_MIN_SUSPICIOUS_LEN = 200
_MIN_SUSPICIOUS_NEWLINES = 2


def _docstring_literal_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def _offenders_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_literal_ids(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        text = node.value
        if len(text) >= _MIN_SUSPICIOUS_LEN and text.count("\n") >= _MIN_SUSPICIOUS_NEWLINES:
            hits.append(f"{path.name}:{node.lineno}")
    return hits


def test_no_prompt_text_in_python_source() -> None:
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        offenders.extend(_offenders_in(path))
    assert not offenders, (
        "prompt-shaped string literal(s) found in src/ — move the text to "
        f"src/devmind/prompts/*.md: {offenders}"
    )


def test_the_detector_would_fire_on_an_actual_prompt_string(tmp_path: Path) -> None:
    sample = tmp_path / "leaky.py"
    sample.write_text(
        'PROMPT = """\n'
        + "You are an autonomous software engineer working one issue on one "
        + "repository.\n\n"
        + "You are in the investigation phase. Your tools are read-only: read "
        + "files, search the code, list directories, find symbols.\n\n"
        + "State the root cause of the issue in one sentence, then make the "
        + "smallest change that fixes it using the edit tools.\n\n"
        + "Finish by calling the finish tool with a calibrated confidence and a "
        + 'self-contained summary of what you established.\n"""\n',
        encoding="utf-8",
    )
    assert _offenders_in(sample)
