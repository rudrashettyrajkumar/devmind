# Spec — E5: Sandbox Execution Layer

| | |
|---|---|
| **Epic** | E5 |
| **Depends on** | E1, E4 |
| **Blocks** | E6, E8 |
| **Size** | L (~2 days) |
| **Skills** | `devmind-standards`, `devmind-testing` |

## Purpose

Run the target repository's commands — installs, test suites, arbitrary allowlisted binaries —
without letting them reach the network or the host filesystem. This is the enforcement point
for safety invariants **SI-2** and **SI-8**.

## Design references

`docs/01-solution-design.md` §3 (SI-2, SI-8), §7 (sandbox).

## Contracts

### `interfaces/sandbox.py`

```python
class Sandbox(ABC):
    @abstractmethod
    async def setup(self, workspace: Path) -> None: ...

    @abstractmethod
    async def run(self, command: SandboxCommand) -> CommandResult: ...

    @abstractmethod
    async def teardown(self) -> None: ...
```

A justified ABC: two implementations ship in v1, plus a `FakeSandbox` in tests. Three
implementations, one contract.

### `schemas/sandbox.py`

```python
class SandboxCommand(BaseModel):
    argv: list[str] = Field(min_length=1)      # argv only — never a shell string
    cwd: str | None = None
    timeout_seconds: int = SANDBOX_COMMAND_TIMEOUT_SECONDS
    env: dict[str, str] = Field(default_factory=dict)

class CommandResult(BaseModel):
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out
```

**`argv: list[str]`, never a command string.** There is no `shell=True` anywhere in this
codebase; the standards auditor greps for it and the safety suite asserts its absence.

### `CommandAllowlist` — SI-8

```python
class CommandAllowlist:
    def __init__(self, allowed: frozenset[str] = ALLOWED_COMMAND_BINARIES) -> None: ...
    def validate(self, argv: list[str]) -> None:
        """Raises SandboxError if argv[0]'s basename is not allowed."""
```

Check `Path(argv[0]).name`, so `/usr/bin/python` and `python` are the same decision and
`./evil` is rejected. Reject argv containing shell metacharacters as a defence-in-depth
measure even though nothing runs through a shell.

### `OutputTruncator`

```python
class OutputTruncator:
    def __init__(self, max_chars: int) -> None: ...
    def truncate(self, text: str) -> tuple[str, bool]: ...
```

Keep head **and** tail with an explicit `... [truncated N of M chars] ...` marker between them.
Tail matters: pytest's summary — the part the self-correction loop actually needs — is at the
end, and a head-only truncation throws away the answer.

### `SubprocessSandbox`

```python
class SubprocessSandbox(Sandbox):
    def __init__(self, allowlist: CommandAllowlist, truncator: OutputTruncator) -> None: ...
```

- `asyncio.create_subprocess_exec(*argv, cwd=..., env=..., start_new_session=True)`.
- **Scrubbed environment.** Build it from an explicit allowlist of variables (`PATH`, `HOME`,
  `LANG`, `PYTHONPATH`), then force `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=/bin/false`,
  `GH_TOKEN=""`, `GITHUB_TOKEN=""`, `ANTHROPIC_API_KEY=""`. The host's credentials must not be
  inherited by repo code — SI-2.
- Timeout via `asyncio.wait_for`; on expiry `os.killpg(os.getpgid(proc.pid), SIGKILL)` — kill
  the whole process group, because a test runner that spawned children will otherwise leave
  orphans holding the workspace.
- `cwd` is resolved through `WorkspacePathGuard` before use.

**Honest limitation.** This is process isolation, not a security boundary: repo code can still
read the host filesystem and open sockets. It is the correct choice for a trusted repo on a
developer machine and the wrong one for an untrusted repo. Log a warning at startup naming this,
document it in the README, and record the backend on the session record.

### `DockerSandbox`

```python
class DockerSandbox(Sandbox):
    def __init__(self, client: DockerClient, image: str,
                 allowlist: CommandAllowlist, truncator: OutputTruncator) -> None: ...
```

Container per session: `network_mode="none"` (**SI-2, enforced by the kernel**), workspace
bind-mounted at `/workspace`, `mem_limit`, `nano_cpus`, `pids_limit`, non-root user,
`read_only=False` only on the workspace mount, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`.
`setup()` creates and starts it; `teardown()` removes it with `force=True` — including on the
failure path, so a crashed run doesn't leak containers.

### `SandboxFactory`

```python
class SandboxFactory:
    def __init__(self, settings: Settings) -> None: ...
    def create(self) -> Sandbox: ...
    def resolve_backend(self) -> SandboxBackend: ...
```

`AUTO` → probe the Docker daemon (`client.ping()`, short timeout); on success `DOCKER`,
otherwise `SUBPROCESS` with a logged warning. `DOCKER` explicitly requested but unavailable is a
`ConfigurationError`, not a silent downgrade — an operator who asked for isolation must not get
less without being told.

The resolved backend is logged once at startup and written to `SessionModel.sandbox_backend`, so
any run's isolation level is knowable after the fact.

### Dependency installation

```python
async def install_dependencies(self, profile: RepoProfile) -> CommandResult
```

Runs `profile.install_command` with `DEPENDENCY_INSTALL_TIMEOUT_SECONDS` (longer than a normal
command). Under Docker, `--network=none` means installs must happen during `setup()` before the
network is dropped, or against a pre-populated image — implement it as a setup-phase step with
network, then run everything else with none. Document whichever you choose in the module
docstring; the distinction is load-bearing.

## Task plan

E5-F1-T1 … E5-F3-T3. Contract and truncator first, then `SubprocessSandbox` (the default dev
path), then Docker, then the factory, then the shared contract suite.

## Testing

The centrepiece is one **parametrised contract suite** both backends must pass:

```python
@pytest.fixture(params=[SandboxBackend.SUBPROCESS, SandboxBackend.DOCKER])
def sandbox(request) -> Sandbox:
    if request.param is SandboxBackend.DOCKER and not docker_available():
        pytest.skip("docker unavailable")
    ...
```

| Assertion | Both backends |
|---|---|
| `echo hello` → exit 0, stdout contains `hello` | ✓ |
| A failing command → non-zero exit, stderr captured | ✓ |
| `sleep 30` with `timeout_seconds=1` → `timed_out=True`, killed within ~2s | ✓ |
| Huge output → truncated with a marker, head and tail both present | ✓ |
| Disallowed binary → `SandboxError`, nothing executed | ✓ |
| `cwd` outside the workspace → `PathEscapeError` | ✓ |
| Environment contains no host tokens | ✓ |
| Network egress fails | Docker asserts; subprocess documents the gap |

Plus: `test_sandbox_factory.py` (AUTO resolution both ways; explicit DOCKER unavailable raises),
and a timeout test asserting **no orphan process survives** the kill.

## Acceptance criteria

- [ ] Both backends pass the same contract suite (Docker skipped-with-reason where absent).
- [ ] Timeouts kill the whole process group; nothing is orphaned.
- [ ] The allowlist rejects unlisted binaries before execution.
- [ ] No `shell=True` anywhere; asserted by a test.
- [ ] Host credentials are absent from the sandbox environment; asserted by a test.
- [ ] The resolved backend is logged and persisted on the session.
- [ ] `make check` green.

## Notes

- **The primary dev machine has no Docker** (WSL2 without Docker Desktop integration). The
  subprocess path is the default developer experience and must be genuinely good — not a
  degraded afterthought. Docker tests skip cleanly with a stated reason; a skipped suite is
  never reported as a passing one.
- Wrap blocking Docker SDK calls in `asyncio.to_thread` so they never stall the event loop.
- Do not add a third backend (gVisor, Firecracker, remote executor). Two implementations already
  justify the ABC; a third with no requirement behind it is exactly what `Claude.md` §9 forbids.
