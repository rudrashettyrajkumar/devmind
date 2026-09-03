"""The wire shape of one Server-Sent Event (E11 §SSE streaming)."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

# The comment line a heartbeat sends; a leading ':' is an SSE comment that clients
# and proxies ignore, but it keeps an idle connection from being reaped.
SSE_HEARTBEAT: str = ": heartbeat\n\n"


class ServerSentEvent(BaseModel):
    """One `text/event-stream` frame. `encode()` is the only serialiser."""

    model_config = ConfigDict(frozen=True)

    id: int
    event: str
    data: dict[str, object]

    def encode(self) -> str:
        """`id:`/`event:`/`data:` lines terminated by a blank line, per the SSE spec."""
        payload = json.dumps(self.data, separators=(",", ":"), default=str)
        return f"id: {self.id}\nevent: {self.event}\ndata: {payload}\n\n"
