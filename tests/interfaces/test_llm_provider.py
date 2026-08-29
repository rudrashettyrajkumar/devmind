from __future__ import annotations

import inspect

import pytest

from devmind.interfaces.llm_provider import LLMProvider
from tests.fakes.fake_llm_provider import FakeLLMProvider


def test_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_complete_is_the_only_abstract_method() -> None:
    assert LLMProvider.__abstractmethods__ == frozenset({"complete"})


def test_fake_provider_satisfies_the_interface() -> None:
    assert issubclass(FakeLLMProvider, LLMProvider)
    assert inspect.iscoroutinefunction(FakeLLMProvider.complete)
