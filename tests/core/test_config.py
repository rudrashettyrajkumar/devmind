import pytest
from pydantic import ValidationError

from devmind.core.config import Settings
from devmind.core.constants import MAX_FIX_ATTEMPTS
from devmind.core.enums import SandboxBackend


def test_settings_loads_with_required_field() -> None:
    settings = Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]
    assert settings.anthropic_api_key == "sk-ant-test"


def test_settings_applies_defaults() -> None:
    settings = Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]
    assert settings.agent_model == "claude-opus-5"
    assert settings.sandbox_backend is SandboxBackend.AUTO
    assert settings.max_fix_attempts == MAX_FIX_ATTEMPTS
    assert settings.dry_run is False
    assert settings.enable_context_editing is False


def test_missing_anthropic_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py sets a placeholder ANTHROPIC_API_KEY so importing devmind.main
    # during collection doesn't fail — remove it here to test the real "fail fast
    # with no key" behavior, and disable .env loading so a local file can't mask it.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("value", [0, 6, -1])
def test_max_fix_attempts_out_of_range_rejected(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(anthropic_api_key="sk-ant-test", max_fix_attempts=value)  # type: ignore[call-arg]


def test_max_session_cost_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(anthropic_api_key="sk-ant-test", max_session_cost_usd=0)  # type: ignore[call-arg]


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-5")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.agent_model == "claude-sonnet-5"
