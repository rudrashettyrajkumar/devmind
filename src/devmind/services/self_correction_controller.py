"""`SelfCorrectionController` — is another fix attempt worth making? (E8-F3).

The controller holds no state of its own: given the parsed report for the run that
just happened and the attempt number, it reads the previous attempt's signature from
`TestRunRepository` and applies four rules in order.

```
1. report.succeeded                     -> SUCCEEDED
2. attempt >= max_attempts              -> EXHAUSTED  ("attempt budget spent")
3. signature == previous_signature      -> EXHAUSTED  ("no progress: identical signature")
4. otherwise                            -> RETRY
```

Rule 3 is the interesting one. An identical signature means the last edit changed
nothing that mattered; spending another attempt re-deriving the same wrong
hypothesis is waste. Escalate to a human instead, and say why.

`EXHAUSTED` is honest: DevMind could not verify a fix, so no PR is offered. Every
attempt stays in the session record for a human to read.
"""

from __future__ import annotations

import logging

from devmind.core.constants import MAX_FIX_ATTEMPTS
from devmind.core.enums import CorrectionAction, EventType
from devmind.repositories.event_repository import EventRepository
from devmind.repositories.test_run_repository import TestRunRepository
from devmind.schemas.test_execution import CorrectionDecision, TestFailureReport

logger = logging.getLogger(__name__)


class SelfCorrectionController:
    """Decides RETRY / EXHAUSTED / SUCCEEDED for one test run."""

    def __init__(
        self,
        runs: TestRunRepository,
        events: EventRepository,
        *,
        max_attempts: int = MAX_FIX_ATTEMPTS,
    ) -> None:
        self._runs = runs
        self._events = events
        self._max_attempts = max_attempts

    def decide(
        self, session_id: str, report: TestFailureReport, attempt: int
    ) -> CorrectionDecision:
        remaining = max(0, self._max_attempts - attempt)

        if report.succeeded:
            return self._decision(CorrectionAction.SUCCEEDED, "the suite is green", remaining)

        if attempt >= self._max_attempts:
            return self._decision(
                CorrectionAction.EXHAUSTED,
                f"attempt budget spent ({attempt}/{self._max_attempts})",
                0,
            )

        previous = self._previous_signature(session_id)
        if previous is not None and report.signature == previous:
            return self._decision(
                CorrectionAction.EXHAUSTED,
                "no progress: identical failure signature to the previous attempt",
                remaining,
            )

        return self._decision(
            CorrectionAction.RETRY,
            f"{report.failed} failing, {report.errors} erroring — a new hypothesis is warranted",
            remaining,
        )

    def record_attempt(
        self,
        session_id: str,
        *,
        attempt: int,
        signature: str,
        decision: CorrectionDecision,
    ) -> None:
        """Emit the `FIX_ATTEMPT` event the orchestrator writes when it loops back to
        `EDITING`. Kept here so the event shape lives next to the decision that fills it.
        """
        self._events.append(
            session_id,
            EventType.FIX_ATTEMPT,
            {
                "attempt": attempt,
                "signature": signature,
                "action": decision.action.value,
                "reason": decision.reason,
                "attempts_remaining": decision.attempts_remaining,
            },
        )

    # --- internals -------------------------------------------------------------

    def _previous_signature(self, session_id: str) -> str | None:
        """The signature of the run before the one just persisted. The current run is
        already the tail of `attempts_for_session`, so the previous is the one before it.
        """
        rows = self._runs.attempts_for_session(session_id)
        if len(rows) < 2:
            return None
        return rows[-2].signature

    @staticmethod
    def _decision(action: CorrectionAction, reason: str, remaining: int) -> CorrectionDecision:
        return CorrectionDecision(action=action, reason=reason, attempts_remaining=remaining)
