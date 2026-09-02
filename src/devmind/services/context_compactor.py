"""`ContextCompactor` — keep a long-horizon phase inside the context window (E7-F1-T4).

Four layers, cheapest first (design §6.1). Layer 1 (tool-result truncation) already
happened at execution time in E6; this class owns the other three, applied together
once the transcript crosses the threshold:

* **Layer 2** — enable the server-side `clear_tool_uses_20250919` strategy on
  subsequent requests. This *clears* stale tool results server-side; it does not
  summarize.
* **Layer 3** — locally blank `read_file` results for files that were later edited.
* **Layer 4** — re-anchor: append the current plan and accumulated diff as one
  compact message, so the goal survives the surgery. This is the load-bearing one —
  an agent that forgets its plan mid-run produces confident nonsense.
"""

from __future__ import annotations

import logging

from devmind.core.constants import CONTEXT_COMPACTION_THRESHOLD
from devmind.services.agent_context import AgentContext

logger = logging.getLogger(__name__)


class ContextCompactor:
    """Decides when a phase's context is too large and shrinks it in place."""

    def __init__(
        self,
        max_context_tokens: int,
        threshold: float = CONTEXT_COMPACTION_THRESHOLD,
    ) -> None:
        self._max_context_tokens = max_context_tokens
        self._threshold = threshold

    @property
    def trigger_tokens(self) -> int:
        """The estimated-token level at or above which compaction runs."""
        return int(self._max_context_tokens * self._threshold)

    async def compact_if_needed(self, ctx: AgentContext) -> bool:
        """Compact `ctx` if it has grown past the threshold. Returns whether it did.

        Idempotent per step: re-anchoring appends one message, so the transcript can
        stay above the threshold for several steps and be re-anchored each time —
        that is intended, the goal restatement is cheap and the alternative is drift.
        """
        estimated = ctx.estimated_tokens
        if estimated < self.trigger_tokens:
            return False

        ctx.enable_context_editing()
        dropped = ctx.drop_superseded_reads()
        ctx.reanchor(ctx.plan_text, ctx.diff_text)
        logger.info(
            "compacted context for session %s: ~%d tokens over the %d trigger; "
            "cleared %d stale read(s), server-side tool-use clearing enabled, plan "
            "and diff re-anchored",
            ctx.session_id,
            estimated,
            self.trigger_tokens,
            dropped,
        )
        return True
