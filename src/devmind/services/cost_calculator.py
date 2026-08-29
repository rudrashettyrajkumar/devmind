"""Turns an API `usage` block into a dollar figure.

Injected into `AnthropicProvider` for per-call logging and, later, into the
per-session budget guard (E7) and the approval payload (E9). The single place model
pricing is applied.
"""

from collections.abc import Mapping
from typing import Final

from devmind.core.constants import (
    CACHE_READ_DISCOUNT,
    CACHE_WRITE_MULTIPLIER,
    MODEL_PRICING,
    ModelPrice,
)
from devmind.exceptions import ConfigurationError
from devmind.schemas.llm import TokenUsage

_TOKENS_PER_MILLION: Final[int] = 1_000_000


class CostCalculator:
    """Computes the USD cost of LLM calls from a pricing table."""

    def __init__(self, pricing: Mapping[str, ModelPrice] = MODEL_PRICING) -> None:
        self._pricing = pricing

    def cost_for(self, model: str, usage: TokenUsage) -> float:
        """USD for a single response's `usage`.

        Fresh input and output tokens bill at the full per-token rate; cache reads at
        `CACHE_READ_DISCOUNT` of the input rate; cache writes at
        `CACHE_WRITE_MULTIPLIER` of it. An unknown model raises `ConfigurationError`
        rather than returning ``0.0`` — a cost ceiling that silently reads zero is
        worse than no ceiling (docs/specs/epic-03 §CostCalculator).
        """
        price = self._price_for(model)
        input_rate = price.input_per_mtok / _TOKENS_PER_MILLION
        output_rate = price.output_per_mtok / _TOKENS_PER_MILLION
        return (
            usage.input_tokens * input_rate
            + usage.cache_read_input_tokens * input_rate * CACHE_READ_DISCOUNT
            + usage.cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
            + usage.output_tokens * output_rate
        )

    def _price_for(self, model: str) -> ModelPrice:
        price = self._pricing.get(model)
        if price is None:
            raise ConfigurationError(
                f"no pricing configured for model {model!r}",
                details={"model": model, "known_models": sorted(self._pricing)},
            )
        return price
