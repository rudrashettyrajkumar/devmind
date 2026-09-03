"""`ChangeSummaryService` — the narrative a human reads before approving (E9-F1-T1).

Renders `change_summary.md` over the final diff, the plan as worked, and the test
evidence, then calls the model. The prompt demands five sections; this service pulls
two of them back out as structured fields:

* **Issue understanding** — the agent's restatement of the problem, which the
  reviewer checks the change against;
* **Risks and uncertainties** — what the agent was unsure about, what it did not
  verify, what to look at hardest.

Both are **required**. A summary that omits either is an unusable response
(`LLMProviderError`) — the uncertainty is the most valuable thing the agent knows,
and a payload without it defeats the point of the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from devmind.exceptions import LLMProviderError
from devmind.interfaces.llm_provider import LLMProvider
from devmind.prompts.loader import PromptLoader
from devmind.schemas.approval import ChangeSummary
from devmind.schemas.llm import LLMRequest
from devmind.schemas.session import SessionRead
from devmind.services.diff_service import DiffService

_PROMPT_NAME: Final[str] = "change_summary"
_UNDERSTANDING_HEADING: Final[str] = "issue understanding"
_RISKS_HEADING: Final[str] = "risks and uncertainties"


class ChangeSummaryService:
    """Turns the final diff + plan + test evidence into a reviewer-facing summary."""

    def __init__(self, llm: LLMProvider, prompts: PromptLoader, diffs: DiffService) -> None:
        self._llm = llm
        self._prompts = prompts
        self._diffs = diffs

    async def summarize(
        self,
        session: SessionRead,
        *,
        plan_text: str,
        test_evidence_text: str,
    ) -> ChangeSummary:
        """Render and parse the change summary for `session`.

        `plan_text` and `test_evidence_text` are assembled by the caller
        (`ApprovalRequestBuilder`) — this service owns only the diff and the model
        call, keeping it free of repositories.
        """
        if session.workspace_path is None:
            raise LLMProviderError(
                f"session {session.id} has no workspace to diff for a change summary",
                details={"session_id": session.id},
            )

        diff = await self._diffs.unified_diff(Path(session.workspace_path))
        meta = self._prompts.load(_PROMPT_NAME).metadata
        rendered = self._prompts.render(
            _PROMPT_NAME,
            issue_title=session.issue_title or session.issue_body or "(no issue text available)",
            todo_plan=plan_text,
            final_diff=diff or "(the working tree has no changes)",
            test_evidence=test_evidence_text,
        )

        response = await self._llm.complete(
            LLMRequest(
                system=self._prompts.render("system_agent"),
                messages=[{"role": "user", "content": [{"type": "text", "text": rendered}]}],
                effort=meta.effort,
            )
        )

        sections = _sections(response.text)
        understanding = sections.get(_UNDERSTANDING_HEADING, "").strip()
        risk_notes = _bullets(sections.get(_RISKS_HEADING, ""))

        if not understanding:
            raise LLMProviderError(
                f"change summary for session {session.id} omitted the required "
                "'Issue understanding' section",
                details={"session_id": session.id},
            )
        if not risk_notes:
            raise LLMProviderError(
                f"change summary for session {session.id} omitted the required "
                "risk notes — an agent that reports only confidence is not useful",
                details={"session_id": session.id},
            )

        return ChangeSummary(
            markdown=response.text.strip(),
            issue_understanding=understanding,
            risk_notes=risk_notes,
        )


def _sections(markdown: str) -> dict[str, str]:
    """Split a markdown body on its `### ` headings into {lowercased heading: body}."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            current = stripped[4:].strip().lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(body).strip() for heading, body in sections.items()}


def _bullets(section_body: str) -> tuple[str, ...]:
    """Every bullet in a section as its own note; a bullet-less paragraph is one note.

    A lone "None identified …" line counts — it is a populated, deliberate statement,
    which is what the prompt asks for when there genuinely are no risks.
    """
    lines = [line.strip() for line in section_body.splitlines() if line.strip()]
    bullets = [line.lstrip("-*").strip() for line in lines if line.startswith(("-", "*"))]
    if bullets:
        return tuple(note for note in bullets if note)
    joined = " ".join(lines).strip()
    return (joined,) if joined else ()
