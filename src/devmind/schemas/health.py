"""Response schema for `GET /health`."""

from pydantic import BaseModel

from devmind.core.enums import SandboxBackend


class HealthRead(BaseModel):
    """What an operator needs to know before starting a session that may run ten minutes.

    `provider_reachable` in E1 reflects only that `ANTHROPIC_API_KEY` is configured —
    a real connectivity check arrives with `AnthropicProvider` in E3. `database` is
    `"not_configured"` until E2 introduces `DatabaseManager`. Both fields keep their
    final shape now so no caller has to change when the real checks land.
    """

    status: str
    version: str
    database: str
    sandbox_backend: SandboxBackend
    provider_reachable: bool
