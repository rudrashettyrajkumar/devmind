"""The one seam to a large language model. See docs/specs/epic-03 §Contracts."""

from abc import ABC, abstractmethod

from devmind.schemas.llm import LLMRequest, LLMResponse


class LLMProvider(ABC):
    """A single typed method.

    Streaming, prompt caching, retries, and SDK-error translation are implementation
    details of a concrete provider — deliberately kept off this surface so callers
    (the agent loop) depend only on `complete()`.

    Two implementations exist: `AnthropicProvider` (services/) in production and
    `FakeLLMProvider` (tests/fakes/) for deterministic tests. That second, real
    implementation is the justification for this ABC under Claude.md §4.
    """

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one turn: send `request`, return the normalized assistant reply."""
        ...
