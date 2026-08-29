"""Unit tests for `DockerSandbox` driven by a fake Docker client.

The real daemon is exercised (skipped-with-reason where absent) by the parametrised
contract suite in `test_sandbox_contract.py`. Here we assert the SDK is *called*
correctly: network disabled, caps dropped, non-root, workspace bound, allowlist and
path-guard enforced before anything is exec'd.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from docker.errors import DockerException

from devmind.core.constants import MAX_TEST_OUTPUT_CHARS
from devmind.exceptions import PathEscapeError, SandboxError
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.services.command_allowlist import CommandAllowlist
from devmind.services.docker_sandbox import DockerSandbox
from devmind.services.output_truncator import OutputTruncator


class _ExecResult:
    def __init__(self, exit_code: int, stdout: bytes, stderr: bytes) -> None:
        self.exit_code = exit_code
        self.output = (stdout, stderr)


class _FakeContainer:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.kwargs = kwargs
        self.short_id = "fakeid"
        self.started = False
        self.removed = False
        self.exec_calls: list[dict[str, Any]] = []
        self.exec_result = _ExecResult(0, b"stdout-here", b"")
        self.remove_raises = False

    def start(self) -> None:
        self.started = True

    def exec_run(self, **kwargs: Any) -> _ExecResult:
        self.exec_calls.append(kwargs)
        return self.exec_result

    def remove(self, *, force: bool = False) -> None:
        if self.remove_raises:
            raise DockerException("cannot remove")
        self.removed = True

    def wait(self, *, timeout: int | None = None) -> dict[str, int]:
        return {"StatusCode": 0}

    def logs(self, *, stdout: bool = True, stderr: bool = True) -> bytes:
        return b"install-log"


class _FakeContainers:
    def __init__(self) -> None:
        self.created: list[_FakeContainer] = []
        self.ran: list[_FakeContainer] = []

    def create(self, image: str, **kwargs: Any) -> _FakeContainer:
        container = _FakeContainer({"image": image, **kwargs})
        self.created.append(container)
        return container

    def run(self, image: str, **kwargs: Any) -> _FakeContainer:
        container = _FakeContainer({"image": image, **kwargs})
        self.ran.append(container)
        return container


class _FakeDockerClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()


@pytest.fixture
def client() -> _FakeDockerClient:
    return _FakeDockerClient()


@pytest.fixture
async def sandbox(client: _FakeDockerClient, tmp_path: Path) -> DockerSandbox:
    workspace = tmp_path / "ws"
    (workspace / "pkg").mkdir(parents=True)
    sb = DockerSandbox(
        client=client,
        image="python:3.12-slim",
        allowlist=CommandAllowlist(),
        truncator=OutputTruncator(MAX_TEST_OUTPUT_CHARS),
    )
    await sb.setup(workspace)
    return sb


async def test_setup_creates_a_locked_down_network_less_container(
    sandbox: DockerSandbox, client: _FakeDockerClient, tmp_path: Path
) -> None:
    container = client.containers.created[0]
    kw = container.kwargs
    assert kw["network_mode"] == "none"
    assert kw["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kw["security_opt"]
    assert kw["user"] != "0" and kw["user"] != "root"
    assert kw["working_dir"] == "/workspace"
    bind = next(iter(kw["volumes"].values()))
    assert bind["bind"] == "/workspace"
    assert container.started is True


async def test_run_execs_argv_in_the_container(
    sandbox: DockerSandbox, client: _FakeDockerClient
) -> None:
    result = await sandbox.run(SandboxCommand(argv=("pytest", "-q")))
    exec_call = client.containers.created[0].exec_calls[0]
    assert exec_call["cmd"] == ["pytest", "-q"]
    assert exec_call["workdir"] == "/workspace"
    assert result.stdout == "stdout-here"
    assert result.succeeded


async def test_run_maps_cwd_under_the_mount(
    sandbox: DockerSandbox, client: _FakeDockerClient
) -> None:
    await sandbox.run(SandboxCommand(argv=("pytest",), cwd="pkg"))
    assert client.containers.created[0].exec_calls[0]["workdir"] == "/workspace/pkg"


async def test_run_before_setup_raises(client: _FakeDockerClient) -> None:
    sb = DockerSandbox(client, "img", CommandAllowlist(), OutputTruncator(100))
    with pytest.raises(SandboxError):
        await sb.run(SandboxCommand(argv=("pytest",)))


async def test_disallowed_binary_never_execs(
    sandbox: DockerSandbox, client: _FakeDockerClient
) -> None:
    with pytest.raises(SandboxError):
        await sandbox.run(SandboxCommand(argv=("curl", "http://x")))
    assert client.containers.created[0].exec_calls == []


async def test_cwd_escape_raises_path_escape(sandbox: DockerSandbox) -> None:
    with pytest.raises(PathEscapeError):
        await sandbox.run(SandboxCommand(argv=("pytest",), cwd="../../etc"))


async def test_timeout_recovers_with_a_fresh_container(
    sandbox: DockerSandbox, client: _FakeDockerClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocking_exec(*_a: object, **_k: object) -> tuple[int, bytes, bytes]:
        time.sleep(3)  # outlives the 0.2s command timeout; wait_for gives up on it
        return 0, b"", b""

    monkeypatch.setattr(sandbox, "_exec", _blocking_exec)
    result = await sandbox.run(SandboxCommand(argv=("pytest",), timeout_seconds=1))
    # SandboxCommand enforces timeout_seconds > 0; 1s is the floor, still well under 3s.
    assert result.timed_out
    assert result.exit_code == -1
    assert len(client.containers.created) == 2  # original + recovery


async def test_teardown_removes_the_container_and_swallows_errors(
    sandbox: DockerSandbox, client: _FakeDockerClient
) -> None:
    client.containers.created[0].remove_raises = True
    await sandbox.teardown()  # must not raise


async def test_install_dependencies_uses_a_throwaway_networked_container(
    sandbox: DockerSandbox, client: _FakeDockerClient
) -> None:
    profile = RepoProfile(language="python", install_command=("uv", "sync"))
    result = await sandbox.install_dependencies(profile)
    assert client.containers.ran, "expected a throwaway container for the install"
    assert client.containers.ran[0].kwargs["network_mode"] == "bridge"
    assert result.exit_code == 0


async def test_install_dependencies_noop_without_a_command(sandbox: DockerSandbox) -> None:
    result = await sandbox.install_dependencies(RepoProfile(language="python"))
    assert result.succeeded
    assert result.argv == ()
