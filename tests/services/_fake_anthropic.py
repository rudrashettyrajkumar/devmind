"""A minimal stand-in for `anthropic.AsyncAnthropic` used by the provider tests.

Records the kwargs of every `create` / `stream` call and returns a pre-built
`anthropic.types.Message` (or raises a pre-set SDK error). No network, ever — the
provider tests assert on request shape and on response parsing.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

from anthropic.types import Message


def build_message(
    *,
    content: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
) -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": content if content is not None else [{"type": "text", "text": "ok"}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage
            or {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
    )


class _FakeStream:
    def __init__(self, result: Message) -> None:
        self._result = result

    async def get_final_message(self) -> Message:
        return self._result


class _FakeStreamManager:
    def __init__(self, result: Message) -> None:
        self._result = result

    async def __aenter__(self) -> _FakeStream:
        return _FakeStream(self._result)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class FakeMessages:
    def __init__(self, result: Message | None, error: BaseException | None) -> None:
        self._result = result
        self._error = error
        self.create_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.create_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    def stream(self, **kwargs: Any) -> _FakeStreamManager:
        self.stream_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return _FakeStreamManager(self._result)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.create_calls + self.stream_calls


class FakeBeta:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


class FakeAsyncAnthropic:
    def __init__(
        self, *, result: Message | None = None, error: BaseException | None = None
    ) -> None:
        if result is None and error is None:
            result = build_message()
        self.messages = FakeMessages(result, error)
        self.beta = FakeBeta(FakeMessages(result, error))
