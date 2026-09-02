"""Every shipped prompt loads, validates, and renders with placeholder values."""

from __future__ import annotations

from pathlib import Path

import pytest

from devmind.prompts.loader import PromptLoader

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "devmind" / "prompts"
_EXPECTED = {
    "system_agent",
    "planner",
    "planner_retry",
    "investigation",
    "patch_author",
    "test_failure_analysis",
    "change_summary",
    "pr_body",
}

_PROMPT_FILES = sorted(p.stem for p in _PROMPTS_DIR.glob("*.md"))


def test_exactly_the_expected_prompts_are_present() -> None:
    assert set(_PROMPT_FILES) == _EXPECTED


@pytest.mark.parametrize("name", _PROMPT_FILES)
def test_prompt_loads_and_metadata_validates(name: str) -> None:
    loaded = PromptLoader(_PROMPTS_DIR).load(name)
    assert loaded.metadata.name == name
    assert loaded.metadata.model == "claude-opus-5"
    assert loaded.metadata.version == "1.0"
    assert loaded.body.strip()


@pytest.mark.parametrize("name", _PROMPT_FILES)
def test_declared_variables_render(name: str) -> None:
    loader = PromptLoader(_PROMPTS_DIR)
    loaded = loader.load(name)
    values = {var: f"<{var}>" for var in loaded.metadata.variables}
    rendered = loader.render(name, **values)
    for var in loaded.metadata.variables:
        assert f"{{{var}}}" not in rendered
        assert f"<{var}>" in rendered


def test_system_agent_is_variable_free_and_states_no_push_capability() -> None:
    loaded = PromptLoader(_PROMPTS_DIR).load("system_agent")
    assert loaded.metadata.variables == ()
    body = loaded.body.lower()
    assert "no command that reaches the network" in body
    assert "pull request" in body


def test_pr_body_prompt_requires_a_named_approver() -> None:
    loaded = PromptLoader(_PROMPTS_DIR).load("pr_body")
    assert "approved_by" in loaded.metadata.variables
