"""`OutputTruncator` — head+tail retention with an explicit marker (E5-F1-T3).

pytest writes its summary — the part the self-correction loop actually needs — at the
*end* of the output. A head-only truncation throws the answer away, so this keeps a
slice of both ends with `... [truncated N of M chars] ...` between them.
"""

from __future__ import annotations

from devmind.core.constants import SANDBOX_TRUNCATION_MARKER


class OutputTruncator:
    """Truncates a string to roughly `max_chars`, keeping its head and its tail."""

    def __init__(self, max_chars: int) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars

    def truncate(self, text: str) -> tuple[str, bool]:
        """Return `(possibly_truncated_text, was_truncated)`.

        When truncation happens the result is `max_chars` of real content plus the
        marker — a small, bounded overshoot of the budget, deliberately, so the
        marker never eats into the retained head or tail.
        """
        total = len(text)
        if total <= self._max_chars:
            return text, False

        head_len = self._max_chars // 2
        tail_len = self._max_chars - head_len
        head = text[:head_len]
        tail = text[total - tail_len :]
        removed = total - head_len - tail_len
        marker = SANDBOX_TRUNCATION_MARKER.format(removed=removed, total=total)
        return f"{head}{marker}{tail}", True

    def truncate_bytes(self, raw: bytes) -> tuple[str, bool]:
        """Decode captured process output (lossily — sandboxed output is not trusted
        to be valid UTF-8) and truncate it. The one place the decode policy lives.
        """
        return self.truncate(raw.decode("utf-8", "replace"))
