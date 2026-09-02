"""DTOs for the agent loop (E7).

`LoopOutcome` is the single return value of `AgentLoop.run()` over one phase. Its
constructors are the only supported way to build one, so a status can never disagree
with the fields that go with it (a `COMPLETED` outcome from a `finish` call always
carries the summary; a `BUDGET_EXHAUSTED` one never does).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from devmind.core.enums import LoopStatus


class FinishSignal(BaseModel):
    """The parsed arguments of a successful `finish` tool call — the model's own
    account of how the phase went. Extracted by `AgentLoop` from the assistant turn,
    not from the tool result, so a malformed `finish` (which the executor turns into
    an error result) simply never produces one of these.
    """

    model_config = ConfigDict(frozen=True)

    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class LoopOutcome(BaseModel):
    """How one phase of the loop ended. Build it with the classmethods below."""

    model_config = ConfigDict(frozen=True)

    status: LoopStatus
    final_text: str = ""
    steps_used: int = Field(default=0, ge=0)
    finish_summary: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def is_completed(self) -> bool:
        return self.status is LoopStatus.COMPLETED

    @classmethod
    def completed(
        cls,
        *,
        steps_used: int,
        final_text: str = "",
        finish: FinishSignal | None = None,
    ) -> LoopOutcome:
        """The phase ended cleanly — an `end_turn`, or an explicit `finish` call whose
        `summary` and `confidence` are then carried through.
        """
        return cls(
            status=LoopStatus.COMPLETED,
            final_text=finish.summary if finish is not None else final_text,
            steps_used=steps_used,
            finish_summary=finish.summary if finish is not None else None,
            confidence=finish.confidence if finish is not None else None,
        )

    @classmethod
    def budget_exhausted(cls, *, steps_used: int) -> LoopOutcome:
        """The step ceiling was reached before the phase finished."""
        return cls(status=LoopStatus.BUDGET_EXHAUSTED, steps_used=steps_used)

    @classmethod
    def cancelled(cls, *, steps_used: int) -> LoopOutcome:
        """A cooperative cancellation was observed at the top of a step."""
        return cls(status=LoopStatus.CANCELLED, steps_used=steps_used)

    @classmethod
    def failed(cls, *, steps_used: int, final_text: str = "") -> LoopOutcome:
        """The model refused or otherwise ended the phase unusably."""
        return cls(status=LoopStatus.FAILED, steps_used=steps_used, final_text=final_text)
