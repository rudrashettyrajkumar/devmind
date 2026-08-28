# Spec — E6: Tool Framework & Tool Suite

| | |
|---|---|
| **Epic** | E6 |
| **Depends on** | E3, E4, E5 |
| **Blocks** | E7, E8 |
| **Size** | L (~2.5 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

The agent's hands. Every capability it has, and — just as important — the boundary of what it
can never do. This epic is where safety invariant **SI-1** becomes structural: the registry
contains no tool that can reach a remote, so the agent cannot push, no matter what it decides.

## Design references

`docs/01-solution-design.md` §3 (SI-1, SI-5, SI-8), §6.2 (tool surface).

## Contracts

### `interfaces/tool.py`

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> ToolName: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_model(self) -> type[BaseModel]: ...

    @abstractmethod
    async def execute(self, payload: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

The JSON schema handed to the API is generated from `input_model.model_json_schema()` — never
hand-written. One definition, so validation and schema cannot drift.

```python
class ToolResult(BaseModel):
    content: str
    is_error: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
```

```python
@dataclass(frozen=True)
class ToolContext:
    session_id: str
    workspace: Path
    guard: WorkspacePathGuard
    sandbox: Sandbox
    profile: RepoProfile
    todos: TodoRepository
```

### `ToolRegistry`

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None: ...           # duplicate name → ConfigurationError
    def get(self, name: str) -> Tool: ...
    def all(self) -> Sequence[Tool]: ...
    def subset(self, names: Collection[ToolName]) -> "ToolRegistry": ...
    def to_api_schemas(self) -> list[dict[str, object]]: ...
```

`subset()` is what gives phases different capabilities — the investigation phase gets read-only
tools, so the agent cannot edit before it has understood anything. That is a design property,
not a suggestion in a prompt.

`to_api_schemas()` emits, per tool: `name`, `description`, `input_schema` (with
`additionalProperties: false` and a complete `required` list), and `strict: true`. It must be
**byte-stable** across calls within a session — sort keys — because the tool block sits at the
front of the cached prefix and any reordering silently destroys the cache.

### `ToolExecutor`

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, events: EventRepository,
                 truncator: OutputTruncator) -> None: ...

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResultBlock: ...
```

Sequence, and every step matters:

1. Look up the tool; unknown name → `is_error` result naming the valid tools.
2. `json.loads`-parsed arguments → `input_model.model_validate(...)`; a `ValidationError`
   becomes an `is_error` result quoting the validation message, so the model can correct itself.
3. Emit `TOOL_CALL` with the arguments.
4. `await tool.execute(...)`.
5. Catch **everything**: `DevMindError` → `is_error` with the message; unexpected `Exception` →
   `is_error` with a generic message, full traceback logged. **A tool error never propagates out
   of the executor.** A crashed tool must not kill a session that could recover.
6. Truncate to `MAX_TOOL_RESULT_CHARS`.
7. Emit `TOOL_RESULT`.

A tool error is information the agent reads and acts on — that is the whole self-correction
premise applied at the tool level.

### The tools

| Tool | Input model | Behaviour |
|---|---|---|
| `list_dir` | `path`, `depth<=3` | gitignore-aware; entry cap |
| `read_file` | `path`, `start_line?`, `end_line?` | Guarded; `MAX_FILE_READ_LINES` cap; binary → error result; line numbers included |
| `search_code` | `pattern`, `glob?`, `max_results<=100` | Delegates to `CodeSearchService` |
| `find_symbol` | `name`, `kind?` | Delegates to `SymbolIndexer` |
| `write_file` | `path`, `content` | Guarded; creates parents; size cap; returns bytes written |
| `apply_patch` | `path`, `old_string`, `new_string` | **Exact match.** 0 matches → error naming the closest context; >1 → error asking for more context; 1 → replace |
| `run_command` | `argv`, `timeout?` | Allowlist + sandbox |
| `run_tests` | `node_ids?`, `keyword?` | Delegates to `TestExecutionService` (E8); E6 ships the tool shell |
| `git_diff` | `paths?` | `git diff` in the workspace, capped at `MAX_DIFF_CHARS` |
| `todo_write` | `items: list[TodoItemWrite]` | Replaces the plan, persists, emits `PLAN_UPDATED` |
| `finish` | `summary`, `confidence` | Structured phase exit |

`apply_patch` deserves the care: ambiguity must fail loudly. Silently patching the first of
three matches is how an agent corrupts a file in a way nobody notices until review. Both failure
messages should tell the model exactly how to succeed next time.

## Task plan

E6-F1-T1 … E6-F4-T3. Framework first, then read tools (safe to test), then write/exec tools,
then the safety suite.

## Testing

Per tool, four cases minimum: happy path, invalid input, path escape (where applicable),
oversized output.

**The safety tests are the point of this epic:**

```python
def test_si1_registry_contains_no_remote_capable_tool(registry: ToolRegistry) -> None:
    forbidden_names = {"push", "pr", "pull", "remote", "fetch", "clone", "curl", "wget"}
    for tool in registry.all():
        assert not (forbidden_names & set(tool.name.split("_")))
        src = inspect.getsource(type(tool)).lower()
        for banned in ("git push", "gh pr", "urlopen", "requests.", "httpx."):
            assert banned not in src


@pytest.mark.parametrize("tool_name", PATH_TAKING_TOOLS)
@pytest.mark.parametrize("escape", ["../../etc/passwd", "/etc/passwd", "a/../../../root"])
async def test_si5_path_taking_tools_reject_escapes(tool_name, escape, tool_context) -> None:
    result = await executor.execute(ToolCall(name=tool_name, arguments={"path": escape}), tool_context)
    assert result.is_error
```

Plus: `run_command` rejects a disallowed binary; the executor converts an exception-raising tool
into an `is_error` result rather than propagating; `to_api_schemas()` output is byte-identical
across two calls.

## Acceptance criteria

- [ ] Every tool is registered, schema-valid, and has `strict: true` with
      `additionalProperties: false`.
- [ ] Every path-taking tool rejects every escape vector.
- [ ] No tool can reach the network; proven by the SI-1 test.
- [ ] A raising tool yields an `is_error` result, never an exception out of the executor.
- [ ] `apply_patch` fails loudly on 0 or >1 matches.
- [ ] `to_api_schemas()` is byte-stable.
- [ ] `make check` green.

## Notes

- **Do not add a generic `bash` tool.** Design §6.2 records the choice: dedicated typed tools
  plus one narrow allowlisted `run_command`. An unrestricted shell would erase both SI-1 and
  SI-8 in a single commit.
- Tool descriptions are read by the model and are load-bearing. Say when to use the tool and
  what it returns; keep them stable, since they live in the cached prefix.
- `run_tests` is a thin shell here — its real implementation arrives with E8. Wire the seam,
  don't duplicate the logic.
