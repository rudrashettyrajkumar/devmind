"""Application settings, loaded once through pydantic-settings.

No `os.environ.get()` call exists anywhere else in this codebase — every configurable
value is a field here. See `.env.example` for the documented list.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from devmind.core.constants import (
    DEFAULT_AGENT_MODEL,
    MAX_AGENT_STEPS_PER_PHASE,
    MAX_FIX_ATTEMPTS,
    SANDBOX_COMMAND_TIMEOUT_SECONDS,
)
from devmind.core.enums import SandboxBackend


class Settings(BaseSettings):
    """Every configurable value in DevMind, typed and validated at startup.

    A bad or missing value fails fast here rather than surfacing as a mystery three
    layers down mid-session.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Providers -----------------------------------------------------------------
    anthropic_api_key: str = Field(
        ..., description="Required. No default — DevMind must not run half-configured."
    )
    github_token: str | None = Field(
        default=None, description="Falls back to the `gh` CLI's own stored auth when unset."
    )

    # --- Persistence -----------------------------------------------------------------
    database_url: str = Field(default="sqlite:///./devmind.db")

    # --- Agent -----------------------------------------------------------------------
    agent_model: str = Field(default=DEFAULT_AGENT_MODEL)
    agent_effort: str = Field(default="high")
    max_fix_attempts: int = Field(default=MAX_FIX_ATTEMPTS, ge=1, le=5)
    max_agent_steps_per_phase: int = Field(default=MAX_AGENT_STEPS_PER_PHASE, ge=1)
    max_session_cost_usd: float = Field(default=5.0, gt=0)

    # --- Sandbox -----------------------------------------------------------------------
    sandbox_backend: SandboxBackend = Field(default=SandboxBackend.AUTO)
    sandbox_command_timeout_seconds: int = Field(default=SANDBOX_COMMAND_TIMEOUT_SECONDS, gt=0)
    sandbox_image: str = Field(default="python:3.12-slim")

    # --- Workspace -----------------------------------------------------------------------
    workspace_root: Path = Field(default=Path("./workspaces"))
    max_concurrent_sessions: int = Field(default=2, ge=1)

    # --- Ops -----------------------------------------------------------------------
    log_level: str = Field(default="INFO")
    dry_run: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    """The single cached `Settings` instance. Depend on this, never `Settings()` directly."""
    return Settings()
