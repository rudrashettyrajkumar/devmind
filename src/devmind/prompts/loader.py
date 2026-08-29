"""Loads and renders the markdown prompt files (Claude.md §8, design §13).

`load()` parses frontmatter into a validated `PromptMetadata`, checks the declared
`name` against the filename stem and the declared `variables` against the `{...}`
placeholders in the body, and caches the result. `render()` substitutes a variable
set that must match the declaration exactly — a missing or unexpected key raises
before the prompt is ever sent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import frontmatter
from pydantic import ValidationError

from devmind.exceptions import PromptError, PromptVariableError
from devmind.schemas.prompt import LoadedPrompt, PromptMetadata

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class PromptLoader:
    """Reads `<name>.md`, validates it, and renders it with named variables."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or _PROMPTS_DIR
        self._cache: dict[str, LoadedPrompt] = {}

    def load(self, name: str) -> LoadedPrompt:
        cached = self._cache.get(name)
        if cached is not None:
            return cached

        path = self._dir / f"{name}.md"
        if not path.is_file():
            raise PromptError(f"no prompt file {name!r}", details={"path": str(path)})

        parsed = frontmatter.load(str(path))
        metadata = self._metadata(name, parsed.metadata)
        body = str(parsed.content)
        self._check_variables(name, metadata, body)

        loaded = LoadedPrompt(metadata=metadata, body=body)
        self._cache[name] = loaded
        return loaded

    def render(self, name: str, **variables: object) -> str:
        loaded = self.load(name)
        declared = set(loaded.metadata.variables)
        provided = set(variables)
        if provided != declared:
            raise PromptVariableError(
                f"prompt {name!r}: the variables passed do not match those declared",
                details={
                    "missing": sorted(declared - provided),
                    "unexpected": sorted(provided - declared),
                },
            )
        return _PLACEHOLDER_RE.sub(lambda match: str(variables[match.group(1)]), loaded.body)

    def _metadata(self, name: str, raw: object) -> PromptMetadata:
        if not isinstance(raw, dict):
            raise PromptError(f"prompt {name!r}: frontmatter is not a mapping")
        try:
            metadata = PromptMetadata.model_validate(
                {str(key): value for key, value in raw.items()}
            )
        except ValidationError as exc:
            raise PromptError(
                f"prompt {name!r}: invalid frontmatter",
                details={"validation_error": str(exc)},
            ) from exc
        if metadata.name != name:
            raise PromptError(
                f"prompt {name!r}: frontmatter declares name {metadata.name!r}, "
                "which must match the filename stem"
            )
        return metadata

    @staticmethod
    def _check_variables(name: str, metadata: PromptMetadata, body: str) -> None:
        used = set(_PLACEHOLDER_RE.findall(body))
        declared = set(metadata.variables)
        if used != declared:
            raise PromptError(
                f"prompt {name!r}: declared variables do not match the body placeholders",
                details={
                    "declared_but_unused": sorted(declared - used),
                    "used_but_undeclared": sorted(used - declared),
                },
            )
