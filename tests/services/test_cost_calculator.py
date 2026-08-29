import pytest

from devmind.core.constants import ModelPrice
from devmind.exceptions import ConfigurationError
from devmind.schemas.llm import TokenUsage
from devmind.services.cost_calculator import CostCalculator


@pytest.fixture
def calc() -> CostCalculator:
    return CostCalculator({"test-model": ModelPrice(input_per_mtok=10.0, output_per_mtok=30.0)})


def test_plain_input_and_output_cost(calc: CostCalculator) -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert calc.cost_for("test-model", usage) == pytest.approx(40.0)


def test_cache_reads_are_discounted(calc: CostCalculator) -> None:
    # 1M cache-read tokens at 10 $/Mtok * 0.1 discount = $1.00
    usage = TokenUsage(cache_read_input_tokens=1_000_000)
    assert calc.cost_for("test-model", usage) == pytest.approx(1.0)


def test_cache_writes_carry_a_premium(calc: CostCalculator) -> None:
    # 1M cache-write tokens at 10 $/Mtok * 1.25 = $12.50
    usage = TokenUsage(cache_creation_input_tokens=1_000_000)
    assert calc.cost_for("test-model", usage) == pytest.approx(12.5)


def test_all_four_token_kinds_sum(calc: CostCalculator) -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    assert calc.cost_for("test-model", usage) == pytest.approx(10.0 + 30.0 + 1.0 + 12.5)


def test_unknown_model_raises_rather_than_costing_zero(calc: CostCalculator) -> None:
    with pytest.raises(ConfigurationError):
        calc.cost_for("no-such-model", TokenUsage(input_tokens=5))


def test_default_pricing_table_knows_the_agent_model() -> None:
    cost = CostCalculator().cost_for("claude-opus-5", TokenUsage(input_tokens=1_000_000))
    assert cost == pytest.approx(5.0)
