import pytest
from pydantic import ValidationError

from devmind.core.enums import Effort
from devmind.schemas.prompt import LoadedPrompt, PromptMetadata


def _valid(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "planner",
        "version": "1.0",
        "model": "claude-opus-5",
        "effort": "high",
        "description": "Turn the issue into a plan",
        "variables": ["issue_title", "repo_brief"],
    }
    base.update(overrides)
    return base


def test_metadata_parses_a_valid_frontmatter_dict() -> None:
    meta = PromptMetadata.model_validate(_valid())
    assert meta.effort is Effort.HIGH
    assert meta.variables == ("issue_title", "repo_brief")


def test_version_float_is_coerced_to_string() -> None:
    meta = PromptMetadata.model_validate(_valid(version=1.0))
    assert meta.version == "1.0"


def test_unknown_model_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PromptMetadata.model_validate(_valid(model="claude-opus-5-20260101"))


def test_unknown_effort_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PromptMetadata.model_validate(_valid(effort="turbo"))


def test_blank_description_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PromptMetadata.model_validate(_valid(description="   "))


@pytest.mark.parametrize("bad", [["1nvalid"], ["has space"], ["class"], ["dup", "dup"]])
def test_invalid_variable_names_are_rejected(bad: list[str]) -> None:
    with pytest.raises(ValidationError):
        PromptMetadata.model_validate(_valid(variables=bad))


def test_metadata_is_frozen() -> None:
    meta = PromptMetadata.model_validate(_valid())
    with pytest.raises(ValidationError):
        meta.name = "other"  # type: ignore[misc]


def test_loaded_prompt_holds_metadata_and_body() -> None:
    meta = PromptMetadata.model_validate(_valid())
    loaded = LoadedPrompt(metadata=meta, body="hello {issue_title}")
    assert loaded.metadata.name == "planner"
    assert "issue_title" in loaded.body
