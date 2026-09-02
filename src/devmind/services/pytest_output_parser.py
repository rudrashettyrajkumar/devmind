"""`PytestOutputParser` — a raw `CommandResult` into a `TestFailureReport` (E8-F2).

A plain class, not an ABC: there is exactly one implementation and no concrete plan
for a second (Claude.md §9). Extract the abstraction the day a JS/jest parser exists.

The two cases that matter most are the ones with no pytest summary at all:

* **Timeout / kill** — `CommandResult.timed_out` is set; there is no output to read.
* **Unparseable** — a non-zero exit with nothing that looks like a pytest summary.

A parser that reported "0 failures" for either would convince the controller the
suite passed. Both are forced to `succeeded is False` here.
"""

from __future__ import annotations

import re
from typing import Final

from devmind.core.constants import (
    MAX_TEST_OUTPUT_CHARS,
    TEST_FAILURE_MAX_ITEMS,
    TEST_FAILURE_MESSAGE_MAX_CHARS,
    TEST_FAILURE_TRACEBACK_MAX_LINES,
)
from devmind.schemas.sandbox import CommandResult
from devmind.schemas.test_execution import TestFailure, TestFailureReport

_TIMEOUT_SIGNATURE: Final[str] = TestFailureReport.mode_signature("__timed_out__")
_UNPARSEABLE_SIGNATURE: Final[str] = TestFailureReport.mode_signature("__unparseable__")

# The trailing `... in 3.44s` clause that every pytest run (pass or fail) ends with,
# and `no tests ran in 0.01s` for an empty selection. Located from the bottom up.
_SUMMARY_LINE_RE: Final[re.Pattern[str]] = re.compile(r"\bin\s+\d+(?:\.\d+)?s\b")
_NO_TESTS_RE: Final[re.Pattern[str]] = re.compile(r"\bno tests ran\b")
_COUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)"
)

_SUMMARY_INFO_HEADER: Final[str] = "short test summary info"
_SECTION_RE: Final[re.Pattern[str]] = re.compile(r"^=+\s+(?P<title>.+?)\s+=+$")
_SUBBLOCK_RE: Final[re.Pattern[str]] = re.compile(r"^_{3,}\s+(?P<title>.+?)\s+_{3,}$")
_INTERRUPTED_RE: Final[re.Pattern[str]] = re.compile(
    r"!!!+\s*Interrupted:.*during collection.*!!!+"
)

# `path/to/test_x.py:12: in test_x` — the first repo frame of a `--tb=short` block.
_FRAME_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+): in ")
_EXC_RE: Final[re.Pattern[str]] = re.compile(
    r"^E\s+(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Failure|Exit))\b"
)
_SUMMARY_FAILED_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<kind>FAILED|ERROR)\s+(?P<node>\S+?)(?:\s+-\s+(?P<msg>.*))?$"
)
# Dependency frames carry no signal for a fix — drop them from the kept traceback.
_NOISE_FRAME_MARKERS: Final[tuple[str, ...]] = (
    "site-packages",
    "/usr/lib/python",
    "/lib/python",
    "<frozen ",
    "importlib",
)


class PytestOutputParser:
    """Turns one pytest invocation's captured output into a `TestFailureReport`."""

    def parse(self, result: CommandResult) -> TestFailureReport:
        combined = self._combine(result)
        tail = combined[-MAX_TEST_OUTPUT_CHARS:]

        if result.timed_out:
            return TestFailureReport(
                timed_out=True, signature=_TIMEOUT_SIGNATURE, truncated_output=tail
            )

        lines = combined.splitlines()
        counts = self._parse_counts(lines)
        if counts is None:
            # No recognisable summary and the run is over — never call this a pass.
            return TestFailureReport(
                unparseable=True, signature=_UNPARSEABLE_SIGNATURE, truncated_output=tail
            )

        summary_rows = self._summary_info_rows(lines)
        blocks = self._detail_blocks(lines)
        collection_error = self._collection_error(lines, summary_rows, blocks)

        failures: list[TestFailure] = []
        if collection_error is None:
            failures = self._build_failures(summary_rows, blocks)

        signature = (
            TestFailureReport.mode_signature(f"collection:{collection_error}")
            if collection_error is not None
            else TestFailureReport.signature_for(failures)
        )

        failed = counts.get("failed", len([r for r in summary_rows if r[0] == "FAILED"]))
        errors = counts.get("errors", len([r for r in summary_rows if r[0] == "ERROR"]))
        return TestFailureReport(
            total=sum(counts.values()),
            passed=counts.get("passed", 0),
            failed=failed,
            errors=errors,
            skipped=counts.get("skipped", 0),
            failures=tuple(failures[:TEST_FAILURE_MAX_ITEMS]),
            collection_error=collection_error,
            signature=signature,
            truncated_output=tail,
        )

    # --- output assembly -----------------------------------------------------------

    @staticmethod
    def _combine(result: CommandResult) -> str:
        parts = [part for part in (result.stdout, result.stderr) if part]
        return "\n".join(parts)

    # --- summary counts ----------------------------------------------------------

    def _parse_counts(self, lines: list[str]) -> dict[str, int] | None:
        """The `N passed, M failed in Xs` line, searched from the bottom. Returns
        `None` when no such line exists — the caller treats that as unparseable.
        """
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped or not _SUMMARY_LINE_RE.search(stripped):
                continue
            if _NO_TESTS_RE.search(stripped):
                return {}
            pairs = _COUNT_RE.findall(stripped)
            if not pairs:
                continue
            counts: dict[str, int] = {}
            for value, word in pairs:
                key = "errors" if word.startswith("error") else word
                counts[key] = counts.get(key, 0) + int(value)
            return counts
        return None

    # --- `short test summary info` section --------------------------------------

    def _summary_info_rows(self, lines: list[str]) -> list[tuple[str, str, str]]:
        """`(kind, node_id, message)` for every `FAILED`/`ERROR` line in the
        summary-info section. `kind` is `"FAILED"` or `"ERROR"`.
        """
        rows: list[tuple[str, str, str]] = []
        for line in self._section_body(lines, _SUMMARY_INFO_HEADER):
            match = _SUMMARY_FAILED_RE.match(line.strip())
            if match is None:
                continue
            rows.append(
                (match.group("kind"), match.group("node"), (match.group("msg") or "").strip())
            )
        return rows

    # --- FAILURES / ERRORS detail sub-blocks ----------------------------------

    def _detail_blocks(self, lines: list[str]) -> dict[str, list[str]]:
        """Map each `___ title ___` sub-block title to its body lines, across both
        the `FAILURES` and `ERRORS` sections.
        """
        blocks: dict[str, list[str]] = {}
        in_detail = False
        current: str | None = None
        for line in lines:
            section = _SECTION_RE.match(line.strip())
            if section is not None:
                in_detail = section.group("title").upper() in {"FAILURES", "ERRORS"}
                current = None
                continue
            if not in_detail:
                continue
            sub = _SUBBLOCK_RE.match(line.strip())
            if sub is not None:
                current = sub.group("title").strip()
                blocks[current] = []
                continue
            if current is not None:
                blocks[current].append(line)
        return blocks

    # --- collection / import errors ------------------------------------------

    def _collection_error(
        self,
        lines: list[str],
        summary_rows: list[tuple[str, str, str]],
        blocks: dict[str, list[str]],
    ) -> str | None:
        interrupted = any(_INTERRUPTED_RE.search(line) for line in lines)
        bare_error = any(kind == "ERROR" and "::" not in node for kind, node, _ in summary_rows)
        collecting_block = next(
            (
                body
                for title, body in blocks.items()
                if title.lower().startswith("error collecting")
            ),
            None,
        )
        if not (interrupted or bare_error or collecting_block is not None):
            return None

        if collecting_block is not None:
            for body_line in collecting_block:
                exc = _EXC_RE.match(body_line.strip())
                if exc is not None:
                    detail = body_line.strip()[1:].strip()
                    return detail[:TEST_FAILURE_MESSAGE_MAX_CHARS]
        return "test collection failed before any test could run"

    # --- failure objects --------------------------------------------------------

    def _build_failures(
        self,
        summary_rows: list[tuple[str, str, str]],
        blocks: dict[str, list[str]],
    ) -> list[TestFailure]:
        failures: list[TestFailure] = []
        for _kind, node_id, message in summary_rows:
            body = self._block_for(node_id, blocks)
            file, line = self._locate(body)
            exception_type = self._exception_type(body)
            failures.append(
                TestFailure(
                    node_id=node_id,
                    file=file,
                    line=line,
                    exception_type=exception_type,
                    message=self._best_message(message, body)[:TEST_FAILURE_MESSAGE_MAX_CHARS],
                    traceback=self._trim_traceback(body),
                )
            )
        return failures

    @staticmethod
    def _block_for(node_id: str, blocks: dict[str, list[str]]) -> list[str]:
        name = node_id.split("::")[-1]
        for title, body in blocks.items():
            candidate = title.removeprefix("ERROR at setup of ").removeprefix(
                "ERROR at teardown of "
            )
            if candidate in (name, node_id):
                return body
        return []

    @staticmethod
    def _locate(body: list[str]) -> tuple[str | None, int | None]:
        for line in body:
            match = _FRAME_RE.match(line.strip())
            if match is not None:
                return match.group("file"), int(match.group("line"))
        return None, None

    @staticmethod
    def _exception_type(body: list[str]) -> str | None:
        for line in body:
            match = _EXC_RE.match(line.strip())
            if match is not None:
                return match.group("exc")
        return None

    @staticmethod
    def _best_message(summary_message: str, body: list[str]) -> str:
        """Prefer a full `E ...` line from the detail block; pytest truncates the
        summary-info message with a trailing `...`. Fall back to the summary.
        """
        error_lines = [line.strip()[1:].strip() for line in body if line.strip().startswith("E ")]
        full = next((line for line in error_lines if not line.endswith("...")), "")
        if full:
            return full
        if summary_message:
            return summary_message
        return error_lines[0] if error_lines else ""

    @staticmethod
    def _trim_traceback(body: list[str]) -> str:
        kept = [
            line
            for line in body
            if line.strip() and not any(marker in line for marker in _NOISE_FRAME_MARKERS)
        ]
        return "\n".join(kept[:TEST_FAILURE_TRACEBACK_MAX_LINES])

    # --- shared section walker ---------------------------------------------------

    @staticmethod
    def _section_body(lines: list[str], header: str) -> list[str]:
        body: list[str] = []
        capturing = False
        for line in lines:
            section = _SECTION_RE.match(line.strip())
            if section is not None:
                capturing = header in section.group("title").lower()
                continue
            if capturing:
                if line.strip().startswith("!!!"):
                    break
                body.append(line)
        return body
