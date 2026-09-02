"""`AgentContext` — the mutable transcript one phase of the loop builds up (E7-F1-T1).

It owns three things: the byte-stable cached prefix (`system` + `tools`), the running
message list, and the step counter. Two rules it exists to enforce, both easy to get
wrong and expensive to debug (spec §AgentContext):

1. **The assistant turn is appended verbatim** (`response.raw_content`). Rebuilding it
   from `.text` drops thinking blocks and breaks continuation.
2. **Every tool result for a turn goes into one user message.** Splitting parallel
   results across messages teaches the model to stop batching tool calls.
"""

from __future__ import annotations

import json
from typing import Final

from devmind.core.constants import TOKEN_ESTIMATE_CHARS_PER_TOKEN
from devmind.core.enums import AgentPhase, ToolName
from devmind.schemas.llm import LLMRequest, LLMResponse, ToolResultBlock

_REANCHOR_HEADER: Final[str] = "## Re-anchor (context was compacted)"


class AgentContext:
    """One phase's conversation state. Not thread-safe — a phase runs sequentially."""

    def __init__(
        self,
        session_id: str,
        system: str,
        tools: list[dict[str, object]],
        step_budget: int,
    ) -> None:
        self.session_id = session_id
        self.plan_text: str = ""
        """The current rendered plan. Set by the orchestrator; re-injected on compaction."""
        self.diff_text: str = ""
        """The most recent `git_diff` result seen this phase — the accumulated change."""

        self._system = system
        self._tools = [dict(tool) for tool in tools]
        self._step_budget = step_budget
        self._allowed_tool_names = frozenset(
            str(tool["name"]) for tool in self._tools if "name" in tool
        )
        self._messages: list[dict[str, object]] = []
        self._steps = 0
        self._context_editing = False

    # --- read-only views ------------------------------------------------------------

    @property
    def step_budget(self) -> int:
        return self._step_budget

    @property
    def steps_used(self) -> int:
        return self._steps

    @property
    def remaining_steps(self) -> int:
        return max(0, self._step_budget - self._steps)

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        """The tool names this phase exposes — `AgentLoop` refuses any call outside it."""
        return self._allowed_tool_names

    @property
    def context_editing_enabled(self) -> bool:
        return self._context_editing

    @property
    def messages(self) -> list[dict[str, object]]:
        """A shallow copy of the transcript — for assertions and compaction passes."""
        return [dict(message) for message in self._messages]

    @property
    def estimated_tokens(self) -> int:
        """A deliberately rough, deliberately high char/token estimate of the whole
        request, used only to decide when the compactor engages.
        """
        chars = len(self._system)
        chars += len(json.dumps(self._tools, default=str))
        for message in self._messages:
            chars += len(json.dumps(message, default=str))
        return chars // TOKEN_ESTIMATE_CHARS_PER_TOKEN

    # --- mutation -----------------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        """Append a plain-text user message — used to seed the phase instruction."""
        self._messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

    def reanchor(self, plan_text: str, diff_text: str) -> None:
        """Re-inject the goal after context surgery: the current plan and the change so
        far, as one compact user message (spec §ContextCompactor, layer 4).
        """
        self.plan_text = plan_text
        self.diff_text = diff_text
        diff_block = diff_text.strip() or "(no changes yet)"
        self.add_user_message(
            f"{_REANCHOR_HEADER}\n\n"
            f"### Current plan\n{plan_text.strip() or '(no plan recorded)'}\n\n"
            f"### Change so far\n{diff_block}\n\n"
            "Older tool output may have been cleared. The plan and diff above are "
            "current. Continue the phase from here."
        )

    def extend(self, response: LLMResponse, results: list[ToolResultBlock]) -> None:
        """Append the assistant turn verbatim, then ALL tool results as one user
        message, and advance the step counter.
        """
        self._messages.append({"role": "assistant", "content": response.raw_content})
        self._messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.tool_use_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                    for block in results
                ],
            }
        )
        self._capture_diff(response, results)
        self._steps += 1

    def enable_context_editing(self) -> None:
        """Turn on the server-side `clear_tool_uses` strategy for subsequent requests."""
        self._context_editing = True

    def drop_superseded_reads(self) -> int:
        """Blank the body of every `read_file` result whose file was later written or
        patched — the current contents are what matter, not a six-step-old snapshot
        (spec §ContextCompactor, layer 3). Returns how many were dropped.
        """
        call_targets = self._call_targets()
        edited = {
            path
            for name, path in call_targets.values()
            if name in {ToolName.WRITE_FILE.value, ToolName.APPLY_PATCH.value} and path
        }
        if not edited:
            return 0

        dropped = 0
        for message in self._messages:
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                target = call_targets.get(str(block.get("tool_use_id")))
                if target is None:
                    continue
                name, path = target
                if name == ToolName.READ_FILE.value and path in edited:
                    if not str(block.get("content", "")).startswith("[stale read"):
                        dropped += 1
                    block["content"] = f"[stale read of {path} dropped after a later edit]"
        return dropped

    # --- request assembly ---------------------------------------------------------

    def to_request(self, phase: AgentPhase) -> LLMRequest:
        """The `LLMRequest` for the next step. `system` and `tools` are byte-stable for
        the life of the phase so the cache prefix never moves; only `messages` and the
        context-editing flag change between steps.
        """
        # `phase` is part of the contract (the loop passes it) but the request is
        # phase-invariant today: the phase-specific instruction is already in the
        # seeded user message, and every loop phase runs at HIGH effort (design §6.1).
        _ = phase
        return LLMRequest(
            system=self._system,
            messages=[dict(message) for message in self._messages],
            tools=[dict(tool) for tool in self._tools],
            enable_context_editing=self._context_editing,
        )

    # --- internals --------------------------------------------------------------

    def _capture_diff(self, response: LLMResponse, results: list[ToolResultBlock]) -> None:
        diff_ids = {call.id for call in response.tool_calls if call.name == ToolName.GIT_DIFF.value}
        if not diff_ids:
            return
        for block in results:
            if block.tool_use_id in diff_ids and not block.is_error:
                self.diff_text = block.content

    def _call_targets(self) -> dict[str, tuple[str, str]]:
        """Map every tool_use id in the transcript to its `(tool_name, path_argument)`."""
        targets: dict[str, tuple[str, str]] = {}
        for message in self._messages:
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = block.get("id")
                name = block.get("name")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    continue
                raw_input = block.get("input")
                path = ""
                if isinstance(raw_input, dict):
                    candidate = raw_input.get("path")
                    if isinstance(candidate, str):
                        path = candidate
                targets[call_id] = (name, path)
        return targets
