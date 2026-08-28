# Engineering Standards — Reference for All Projects

This is a reusable coding-standards file. Attach it to any project prompt given to
Claude Code so every project follows the same industry-level pattern. It defines
**how** to build, not **what** to build (project details are separate files).

## Guiding philosophy
- Full OOP, but pragmatic. SOLID principles guide design decisions; YAGNI and KISS
  set the limit on how far to take them.
- Add an abstraction (interface, repository, service layer) only where it earns its
  keep — a real second implementation, a real testing boundary, or a real swap
  requirement. Don't add one "just in case."
- When in doubt: build the simple version first, refactor toward the pattern the
  moment a second concrete need for it appears — not before.

---

## 1. Project structure — src layout with clear layer separation
```
project-root/
├── src/
│   └── app_name/
│       ├── api/              # FastAPI routers — interface layer only
│       ├── services/         # business logic — orchestrates use cases
│       ├── repositories/     # data access layer (all SQLAlchemy usage lives here)
│       ├── models/           # SQLAlchemy ORM models
│       ├── schemas/          # Pydantic models (request/response DTOs)
│       ├── interfaces/       # abstract base classes ("ports")
│       ├── core/
│       │   ├── config.py     # pydantic-settings
│       │   ├── constants.py  # every literal used more than once
│       │   └── enums.py      # closed-set values
│       ├── prompts/          # markdown prompt files + yaml metadata
│       └── exceptions/       # custom exception classes
├── tests/                    # mirrors src/ structure
├── pyproject.toml
└── .env.example
```
**Rule:** each layer only talks to the layer directly below it. The API layer never
touches a SQLAlchemy model directly; services never construct a `Response` object;
repositories never contain business logic.

---

## 2. Pydantic — every payload is a typed model, never a raw dict
- All request/response bodies are Pydantic `BaseModel`s, living in `schemas/`.
- Settings are loaded through `pydantic-settings.BaseSettings`, not scattered
  `os.environ.get()` calls.
- Convert ORM objects to schemas with `model_config = ConfigDict(from_attributes=True)`.

```python
# core/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    database_url: str = Field(...)
    anthropic_api_key: str = Field(...)
    max_retries: int = Field(default=3)

# schemas/case.py
from pydantic import BaseModel, ConfigDict

class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: "CaseStatus"   # enum, not a string — see section 6
```

---

## 3. SQLAlchemy ORM (2.0 style) + Repository pattern
- Models use `DeclarativeBase`.
- **No service or API code ever imports `Session` directly** — all DB access goes
  through a repository class.
- Sessions are managed with a context manager so they always close cleanly.

```python
# models/case.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class CaseModel(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str]

# repositories/case_repository.py
from sqlalchemy.orm import Session
from src.app_name.models.case import CaseModel

class CaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, case_id: str) -> CaseModel | None:
        return self._session.get(CaseModel, case_id)

    def save(self, case: CaseModel) -> None:
        self._session.add(case)
        self._session.commit()
```

---

## 4. Abstract Base Classes — interfaces for genuinely swappable components
Use `abc.ABC` for components where more than one implementation realistically
exists — an LLM provider, a vector store, a notification channel. This is the
Dependency Inversion Principle: high-level code depends on the abstraction, not a
concrete class, so implementations can be swapped or mocked in tests.

```python
# interfaces/llm_provider.py
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str: ...

# services/anthropic_provider.py
class AnthropicProvider(LLMProvider):
    async def generate(self, prompt: str) -> str:
        ...  # real call here
```
**Don't** create an ABC for something with exactly one implementation and no
concrete plan to add a second — that's the over-engineering YAGNI warns against.

---

## 5. Full OOP — no loose top-level scripts
- Every unit of logic lives inside a class.
- Services are classes with dependencies passed into `__init__` (constructor
  injection) — not module-level functions grabbing globals.
- Avoid a catch-all `utils.py` full of unrelated functions; group related behaviour
  into a class instead (e.g. a `TextSanitizer` class rather than five loose
  `clean_x()` functions).

```python
class CaseTriageService:
    def __init__(self, repo: CaseRepository, llm: LLMProvider) -> None:
        self._repo = repo
        self._llm = llm

    async def triage(self, case_id: str) -> CaseRead:
        case = self._repo.get_by_id(case_id)
        ...
```

---

## 6. Modular prompting — markdown files + YAML metadata
- One `.md` file per prompt in `prompts/`, YAML frontmatter for metadata, markdown
  body for the actual prompt text. This keeps prompt content out of Python strings
  entirely and lets you version/diff prompts like real content.

```markdown
---
name: case_extraction
version: 1.2
model: claude-sonnet
temperature: 0.1
description: Extracts structured fields from a submitted case document
---

You are extracting structured fields from a case document.
Return only the fields defined in the schema. Do not infer missing fields.
```

```python
# prompts/loader.py
from pathlib import Path
import yaml
import frontmatter  # python-frontmatter package

class PromptLoader:
    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir

    def load(self, name: str) -> tuple[dict, str]:
        post = frontmatter.load(self._dir / f"{name}.md")
        return post.metadata, post.content
```

---

## 7. Enums — no bare strings for any closed set of values
Any field with a fixed set of valid values (status, role, task type, provider name)
is a `StrEnum`, never a raw string. Typos become import-time/type-check errors
instead of silent runtime bugs.

```python
# core/enums.py
from enum import StrEnum

class CaseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    ESCALATED = "escalated"
    REJECTED = "rejected"

    def is_terminal(self) -> bool:
        return self in (CaseStatus.APPROVED, CaseStatus.REJECTED)
```

---

## 8. Constants — single source of truth, nothing hardcoded inline
`core/constants.py` holds every literal used more than once, or any literal that
could plausibly need to change (thresholds, default timeouts, model names). Mark
them `Final` so a type checker flags accidental reassignment.

```python
# core/constants.py
from typing import Final

MAX_RETRY_ATTEMPTS: Final[int] = 3
RISK_ESCALATION_THRESHOLD: Final[float] = 0.75
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final[int] = 30
```
Business logic references `RISK_ESCALATION_THRESHOLD`, never the literal `0.75`
typed inline somewhere in a service.

---

## 9. Guardrails against over-engineering (YAGNI / KISS — apply these literally)
- No ABC/interface for a component with a single implementation and no near-term
  plan to swap it.
- No repository class for a one-off script that touches a table once.
- No enum for a value used exactly once with no risk of typos elsewhere.
- No config flag for something that will never realistically change.
- No premature microservice split, queue, or cache layer unless the project's
  actual current requirement demands it — not "for scale later."
- If you catch yourself building an abstraction to satisfy a rule in this document
  rather than a real need in the project, stop and use the plain version instead.