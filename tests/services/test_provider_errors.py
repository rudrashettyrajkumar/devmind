from __future__ import annotations

from typing import cast

import anthropic
import httpx2
import pytest
from anthropic import AsyncAnthropic

from devmind.core.config import Settings
from devmind.exceptions import LLMProviderError
from devmind.schemas.llm import LLMRequest
from devmind.services.anthropic_provider import AnthropicProvider
from devmind.services.cost_calculator import CostCalculator
from tests.services._fake_anthropic import FakeAsyncAnthropic

_REQUEST_URL = "https://api.anthropic.com/v1/messages"


@pytest.fixture
def settings() -> Settings:
    return Settings(anthropic_api_key="sk-ant-test")  # type: ignore[call-arg]


def _provider(error: BaseException, settings: Settings) -> AnthropicProvider:
    fake = FakeAsyncAnthropic(error=error)
    return AnthropicProvider(cast(AsyncAnthropic, fake), settings, CostCalculator())


def _response(status: int, headers: dict[str, str] | None = None) -> httpx2.Response:
    request = httpx2.Request("POST", _REQUEST_URL)
    return httpx2.Response(status, headers=headers or {}, request=request)


def _request() -> LLMRequest:
    return LLMRequest(system="s", messages=[{"role": "user", "content": "hi"}], max_tokens=1_000)


async def test_not_found_maps_to_non_retryable_llm_provider_error(settings: Settings) -> None:
    exc = anthropic.NotFoundError("bad model", response=_response(404), body=None)
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is False
    assert caught.value.__cause__ is exc


async def test_rate_limit_maps_to_retryable_and_keeps_retry_after(settings: Settings) -> None:
    exc = anthropic.RateLimitError(
        "slow down", response=_response(429, {"retry-after": "30"}), body=None
    )
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is True
    assert caught.value.details["retry_after"] == "30"


async def test_server_error_status_is_retryable(settings: Settings) -> None:
    exc = anthropic.InternalServerError("boom", response=_response(503), body=None)
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is True
    assert caught.value.details["status_code"] == 503


async def test_client_error_status_is_not_retryable(settings: Settings) -> None:
    exc = anthropic.BadRequestError("bad params", response=_response(400), body=None)
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is False
    assert caught.value.details["status_code"] == 400


async def test_connection_error_maps_to_retryable(settings: Settings) -> None:
    exc = anthropic.APIConnectionError(request=httpx2.Request("POST", _REQUEST_URL))
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is True


async def test_other_sdk_api_errors_do_not_escape_the_provider_seam(settings: Settings) -> None:
    exc = anthropic.APIError("unexpected", request=httpx2.Request("POST", _REQUEST_URL), body=None)
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert caught.value.details["retryable"] is False
    assert caught.value.__cause__ is exc


async def test_most_specific_handler_wins_not_found_before_api_status(settings: Settings) -> None:
    # NotFoundError subclasses APIStatusError; a broad handler would mislabel it retryable.
    exc = anthropic.NotFoundError("nope", response=_response(404), body=None)
    with pytest.raises(LLMProviderError) as caught:
        await _provider(exc, settings).complete(_request())
    assert "model not found" in str(caught.value)
    assert caught.value.details["retryable"] is False
