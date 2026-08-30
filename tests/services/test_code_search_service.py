from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from devmind.core.constants import CODE_SEARCH_MAX_LINE_CHARS
from devmind.services.code_search_service import CodeSearchService
from devmind.services.subprocess_command_runner import SubprocessCommandRunner
from tests.fakes.fake_command_runner import FakeCommandRunner, command_output


@pytest.fixture
def haystack(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def target():\n    return 1\n\n# target again\n")
    (tmp_path / "b.txt").write_text("nothing here\n")
    (tmp_path / "long.py").write_text("x = 'target' + '" + "z" * 2000 + "'\n")
    return tmp_path


@pytest.fixture
def force_grep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the service onto its `grep -rn` fallback regardless of whether the host
    has ripgrep installed, so the fallback path is always exercised.
    """
    monkeypatch.setattr(shutil, "which", lambda _: None)


@pytest.mark.usefixtures("force_grep")
async def test_grep_fallback_returns_structured_hits(haystack: Path) -> None:
    service = CodeSearchService(SubprocessCommandRunner(default_timeout=15))
    hits = await service.search(haystack, "target")
    paths = {hit.path for hit in hits}
    assert "a.py" in paths
    assert all(hit.line > 0 for hit in hits)


@pytest.mark.usefixtures("force_grep")
async def test_lines_are_truncated(haystack: Path) -> None:
    service = CodeSearchService(SubprocessCommandRunner(default_timeout=15))
    hits = await service.search(haystack, "target")
    assert all(len(hit.text) <= CODE_SEARCH_MAX_LINE_CHARS + 20 for hit in hits)


@pytest.mark.usefixtures("force_grep")
async def test_max_results_caps_output(haystack: Path) -> None:
    service = CodeSearchService(SubprocessCommandRunner(default_timeout=15))
    hits = await service.search(haystack, "target", max_results=1)
    assert len(hits) == 1


async def test_ripgrep_json_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")
    rg_json = "\n".join(
        [
            json.dumps({"type": "begin", "data": {"path": {"text": "./a.py"}}}),
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "./a.py"},
                        "line_number": 12,
                        "lines": {"text": "    do_target()\n"},
                    },
                }
            ),
            json.dumps({"type": "end", "data": {"path": {"text": "./a.py"}}}),
        ]
    )
    runner = FakeCommandRunner(by_prefix={("rg",): command_output(["rg"], stdout=rg_json)})
    service = CodeSearchService(runner)

    hits = await service.search(Path("/somewhere"), "target")

    assert len(hits) == 1
    assert hits[0].path == "a.py"
    assert hits[0].line == 12
    assert hits[0].text == "    do_target()"


async def test_no_matches_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")
    runner = FakeCommandRunner(by_prefix={("rg",): command_output(["rg"], exit_code=1, stdout="")})
    service = CodeSearchService(runner)
    assert await service.search(Path("/x"), "nope") == []


async def test_ripgrep_skips_malformed_and_non_match_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")
    stdout = "\n".join(
        [
            "not json at all",
            json.dumps({"type": "context", "data": {"lines": {"text": "ctx"}}}),
            json.dumps({"type": "match", "data": {"path": {"text": None}, "line_number": 1}}),
            json.dumps(
                {
                    "type": "match",
                    "data": {
                        "path": {"text": "keep.py"},
                        "line_number": 3,
                        "lines": {"text": "hit\n"},
                    },
                }
            ),
        ]
    )
    runner = FakeCommandRunner(by_prefix={("rg",): command_output(["rg"], stdout=stdout)})
    hits = await CodeSearchService(runner).search(Path("/x"), "hit")
    assert [(h.path, h.line) for h in hits] == [("keep.py", 3)]


async def test_glob_is_passed_through_to_ripgrep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")
    runner = FakeCommandRunner(by_prefix={("rg",): command_output(["rg"], stdout="")})
    await CodeSearchService(runner).search(Path("/x"), "p", glob="*.py")
    assert "--glob" in runner.calls[0].argv
    assert "*.py" in runner.calls[0].argv
