from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from devmind.exceptions import PromptError, PromptVariableError
from devmind.prompts.loader import PromptLoader


def _write(dir_: Path, name: str, text: str) -> None:
    (dir_ / f"{name}.md").write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "greeter",
        """
        ---
        name: greeter
        version: "1.0"
        model: claude-opus-5
        effort: low
        description: Greets someone by name
        variables:
          - who
        ---

        Say hello to {who}, warmly.
        """,
    )
    return tmp_path


@pytest.fixture
def loader(prompts_dir: Path) -> PromptLoader:
    return PromptLoader(prompts_dir)


def test_load_parses_metadata_and_body(loader: PromptLoader) -> None:
    loaded = loader.load("greeter")
    assert loaded.metadata.name == "greeter"
    assert loaded.metadata.variables == ("who",)
    assert "{who}" in loaded.body


def test_load_is_cached(loader: PromptLoader) -> None:
    assert loader.load("greeter") is loader.load("greeter")


def test_render_substitutes_declared_variables(loader: PromptLoader) -> None:
    assert loader.render("greeter", who="Sam") == "Say hello to Sam, warmly."


def test_render_missing_variable_raises(loader: PromptLoader) -> None:
    with pytest.raises(PromptVariableError) as caught:
        loader.render("greeter")
    assert caught.value.details["missing"] == ["who"]


def test_render_unexpected_variable_raises(loader: PromptLoader) -> None:
    with pytest.raises(PromptVariableError) as caught:
        loader.render("greeter", who="Sam", extra="nope")
    assert caught.value.details["unexpected"] == ["extra"]


def test_missing_file_raises_prompt_error(loader: PromptLoader) -> None:
    with pytest.raises(PromptError):
        loader.load("does_not_exist")


def test_name_mismatch_raises(prompts_dir: Path) -> None:
    _write(
        prompts_dir,
        "misnamed",
        """
        ---
        name: something_else
        version: "1.0"
        model: claude-opus-5
        effort: low
        description: x
        variables: []
        ---
        body
        """,
    )
    with pytest.raises(PromptError, match="filename stem"):
        PromptLoader(prompts_dir).load("misnamed")


def test_declared_variable_not_used_in_body_raises(prompts_dir: Path) -> None:
    _write(
        prompts_dir,
        "extra_decl",
        """
        ---
        name: extra_decl
        version: "1.0"
        model: claude-opus-5
        effort: low
        description: x
        variables:
          - used
          - unused
        ---
        Only {used} appears here.
        """,
    )
    with pytest.raises(PromptError, match="declared variables"):
        PromptLoader(prompts_dir).load("extra_decl")


def test_undeclared_placeholder_in_body_raises(prompts_dir: Path) -> None:
    _write(
        prompts_dir,
        "leaky",
        """
        ---
        name: leaky
        version: "1.0"
        model: claude-opus-5
        effort: low
        description: x
        variables:
          - declared
        ---
        {declared} and a sneaky {undeclared} token.
        """,
    )
    with pytest.raises(PromptError, match="declared variables"):
        PromptLoader(prompts_dir).load("leaky")


def test_non_mapping_frontmatter_raises_prompt_error(loader: PromptLoader) -> None:
    with pytest.raises(PromptError, match="not a mapping"):
        loader._metadata("greeter", ["not", "a", "mapping"])


def test_invalid_frontmatter_raises_prompt_error(prompts_dir: Path) -> None:
    _write(
        prompts_dir,
        "bad_model",
        """
        ---
        name: bad_model
        version: "1.0"
        model: gpt-4o
        effort: low
        description: x
        variables: []
        ---
        body
        """,
    )
    with pytest.raises(PromptError, match="invalid frontmatter"):
        PromptLoader(prompts_dir).load("bad_model")
