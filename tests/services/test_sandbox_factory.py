from __future__ import annotations

import pytest
from docker.errors import DockerException

from devmind.core.config import Settings
from devmind.core.enums import SandboxBackend
from devmind.exceptions import ConfigurationError
from devmind.services import sandbox_factory as sf
from devmind.services.docker_sandbox import DockerSandbox
from devmind.services.sandbox_factory import SandboxFactory
from devmind.services.subprocess_sandbox import SubprocessSandbox


def _settings(backend: SandboxBackend) -> Settings:
    return Settings(anthropic_api_key="sk-ant-test", sandbox_backend=backend)  # type: ignore[call-arg]


class _FakeDockerModule:
    def __init__(self, *, pingable: bool) -> None:
        self._pingable = pingable
        self.from_env_calls = 0

    def from_env(self, *_args: object, **_kwargs: object) -> _FakeDockerClient:
        self.from_env_calls += 1
        return _FakeDockerClient(pingable=self._pingable)


class _FakeDockerClient:
    def __init__(self, *, pingable: bool) -> None:
        self._pingable = pingable

    def ping(self) -> bool:
        if not self._pingable:
            raise DockerException("daemon unreachable")
        return True


@pytest.fixture
def docker_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sf, "docker", _FakeDockerModule(pingable=True))


@pytest.fixture
def docker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sf, "docker", _FakeDockerModule(pingable=False))


@pytest.mark.usefixtures("docker_up")
def test_auto_resolves_to_docker_when_daemon_is_up() -> None:
    factory = SandboxFactory(_settings(SandboxBackend.AUTO))
    assert factory.resolve_backend() is SandboxBackend.DOCKER


@pytest.mark.usefixtures("docker_down")
def test_auto_falls_back_to_subprocess_when_daemon_is_down() -> None:
    factory = SandboxFactory(_settings(SandboxBackend.AUTO))
    assert factory.resolve_backend() is SandboxBackend.SUBPROCESS


@pytest.mark.usefixtures("docker_down")
def test_explicit_docker_unavailable_raises_configuration_error() -> None:
    factory = SandboxFactory(_settings(SandboxBackend.DOCKER))
    with pytest.raises(ConfigurationError):
        factory.resolve_backend()


@pytest.mark.usefixtures("docker_down")
def test_explicit_subprocess_never_probes_docker() -> None:
    factory = SandboxFactory(_settings(SandboxBackend.SUBPROCESS))
    assert factory.resolve_backend() is SandboxBackend.SUBPROCESS


@pytest.mark.usefixtures("docker_down")
def test_create_builds_a_subprocess_sandbox() -> None:
    sandbox = SandboxFactory(_settings(SandboxBackend.SUBPROCESS)).create()
    assert isinstance(sandbox, SubprocessSandbox)


@pytest.mark.usefixtures("docker_up")
def test_create_builds_a_docker_sandbox_when_resolved_to_docker() -> None:
    sandbox = SandboxFactory(_settings(SandboxBackend.DOCKER)).create()
    assert isinstance(sandbox, DockerSandbox)
