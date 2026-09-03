"""`PrBodyComposer` — renders the draft PR body and guarantees its provenance footer (E10-F2-T2).

The narrative sections (`## Summary`, `## The issue`, `## Changes`, `## Test evidence`,
`## Risks and what to review closely`) come from the model via `pr_body.md`. The
`## Provenance` footer does **not**: it is appended here, deterministically, from
facts DevMind knows — the session id, the approving human, the timestamp, the
sandbox, the model, and the cost. A reviewer must never have to guess whether a human
looked at this or whether it was merged, so that footer is never left to the model to
remember (spec §"PR body").

A rendered body missing any mandatory heading is an unusable response
(`LLMProviderError`) — the same contract `ChangeSummaryService` holds for its sections.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from devmind.core.constants import (
    PR_BODY_DRAFT_NOTICE,
    PR_BODY_NO_ISSUE_REFERENCE,
    PR_BODY_PROVENANCE_HEADING,
    PR_BODY_REQUIRED_HEADINGS,
)
from devmind.exceptions import LLMProviderError
from devmind.interfaces.llm_provider import LLMProvider
from devmind.prompts.loader import PromptLoader
from devmind.schemas.approval import (
    ApprovalRecord,
    ApprovalRequest,
    TestEvidence,
    TestRunSummary,
)
from devmind.schemas.llm import LLMRequest
from devmind.schemas.session import SessionRead

_PROMPT_NAME: Final[str] = "pr_body"


class PrBodyComposer:
    """Turns the approved review payload into the final PR body markdown."""

    def __init__(self, llm: LLMProvider, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def compose(
        self,
        *,
        session: SessionRead,
        review: ApprovalRequest,
        approval: ApprovalRecord,
        model: str,
        max_fix_attempts: int,
    ) -> str:
        """Render `pr_body.md`, verify its sections, and append the provenance footer."""
        evidence_block = self.render_evidence(review.test_evidence, max_fix_attempts)
        meta = self._prompts.load(_PROMPT_NAME).metadata
        rendered = self._prompts.render(
            _PROMPT_NAME,
            issue_reference=self._issue_reference(session),
            change_summary=review.summary.markdown,
            test_evidence=evidence_block,
            attempts_used=str(review.metrics.fix_attempts),
            approved_by=approval.decided_by or "an authorized reviewer",
        )
        response = await self._llm.complete(
            LLMRequest(
                system=self._prompts.render("system_agent"),
                messages=[{"role": "user", "content": [{"type": "text", "text": rendered}]}],
                effort=meta.effort,
            )
        )
        prose = response.text.strip()
        self._require_headings(session.id, prose)
        return f"{prose}\n\n{self._provenance(session, review, approval, model)}"

    # --- evidence --------------------------------------------------------

    @staticmethod
    def render_evidence(evidence: TestEvidence, max_fix_attempts: int) -> str:
        """The compact baseline / final / attempts block the spec shows in the body."""
        if evidence.unverified:
            return "UNVERIFIED — no test suite ran for this session."

        def line(label: str, run: TestRunSummary | None) -> str:
            if run is None:
                return f"{label:<9}(none)"
            suffix = f", {run.errors} error(s)" if run.errors else ""
            return f"{label:<9}{run.passed} passed, {run.failed} failed{suffix}"

        lines = [line("baseline:", evidence.baseline), line("final:", evidence.final)]
        if evidence.pre_existing_failures:
            lines.append(
                "pre-existing (excluded from the verdict): "
                + ", ".join(evidence.pre_existing_failures)
            )
        used = len(evidence.attempts) if evidence.attempts else 0
        lines.append(f"fix attempts used: {used} of {max_fix_attempts}")
        return "\n".join(lines)

    # --- internals ------------------------------------------------------

    @staticmethod
    def _issue_reference(session: SessionRead) -> str:
        if session.issue_number is not None:
            return f"#{session.issue_number}"
        return PR_BODY_NO_ISSUE_REFERENCE

    @staticmethod
    def _require_headings(session_id: str, prose: str) -> None:
        lowered = prose.lower()
        missing = [h for h in PR_BODY_REQUIRED_HEADINGS if h.lower() not in lowered]
        if missing:
            raise LLMProviderError(
                f"the rendered PR body for session {session_id} is missing required "
                f"section(s): {', '.join(missing)}",
                details={"session_id": session_id, "missing": missing},
            )

    @staticmethod
    def _provenance(
        session: SessionRead,
        review: ApprovalRequest,
        approval: ApprovalRecord,
        model: str,
    ) -> str:
        decided_at = approval.decided_at or datetime.now(UTC)
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=UTC)
        sandbox = session.sandbox_backend.value if session.sandbox_backend else "unknown"
        return (
            f"{PR_BODY_PROVENANCE_HEADING}\n\n"
            f"Produced autonomously by DevMind (session `{session.id}`), reviewed and "
            f"approved by {approval.decided_by or 'an authorized reviewer'} on "
            f"{decided_at.strftime('%Y-%m-%d %H:%M UTC')}. "
            f"Sandbox: {sandbox}. Model: {model}. "
            f"Cost: ${review.metrics.cost_usd:.2f}. {PR_BODY_DRAFT_NOTICE}"
        )
