from devmind.core.constants import (
    ALLOWED_COMMAND_BINARIES,
    CACHE_READ_DISCOUNT,
    MAX_FIX_ATTEMPTS,
    MODEL_PRICING,
)


def test_max_fix_attempts_matches_settings_default() -> None:
    from devmind.core.config import Settings

    settings = Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]
    assert settings.max_fix_attempts == MAX_FIX_ATTEMPTS


def test_allowed_command_binaries_is_a_frozenset() -> None:
    assert isinstance(ALLOWED_COMMAND_BINARIES, frozenset)
    assert "python" in ALLOWED_COMMAND_BINARIES
    assert "rm" not in ALLOWED_COMMAND_BINARIES


def test_model_pricing_has_the_configured_agent_model() -> None:
    assert "claude-opus-5" in MODEL_PRICING
    price = MODEL_PRICING["claude-opus-5"]
    assert price.input_per_mtok == 5.0
    assert price.output_per_mtok == 25.0


def test_cache_read_discount_is_a_fraction() -> None:
    assert 0.0 < CACHE_READ_DISCOUNT < 1.0
