"""DTOs for the markdown prompt system (Claude.md §8, docs/01-solution-design.md §13)."""

import keyword

from pydantic import BaseModel, ConfigDict, field_validator

from devmind.core.constants import MODEL_PRICING
from devmind.core.enums import Effort


class PromptMetadata(BaseModel):
    """The validated YAML frontmatter of one `prompts/*.md` file.

    `PromptLoader` additionally checks `name` against the filename stem and the
    declared `variables` against the placeholders in the body.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    model: str
    effort: Effort
    description: str
    variables: tuple[str, ...] = ()

    @field_validator("version", mode="before")
    @classmethod
    def _stringify_version(cls, value: object) -> str:
        # YAML parses `version: 1.0` as a float; the frontmatter files quote it, but
        # coerce here too so an unquoted value is not a load failure.
        return str(value)

    @field_validator("name", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("model")
    @classmethod
    def _known_model(cls, value: str) -> str:
        if value not in MODEL_PRICING:
            raise ValueError(
                f"unknown model {value!r} — must be an exact id from "
                f"{sorted(MODEL_PRICING)} with no date suffix"
            )
        return value

    @field_validator("variables")
    @classmethod
    def _valid_identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate variable names")
        for name in value:
            if not name.isidentifier() or keyword.iskeyword(name):
                raise ValueError(f"{name!r} is not a valid variable name")
        return value


class LoadedPrompt(BaseModel):
    """A parsed prompt: validated metadata plus the markdown body. The return type of
    `PromptLoader.load()`.
    """

    model_config = ConfigDict(frozen=True)

    metadata: PromptMetadata
    body: str
