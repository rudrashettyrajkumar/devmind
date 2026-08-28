from unittest.mock import patch

from devmind.core.enums import SandboxBackend
from devmind.services.sandbox_backend_probe import SandboxBackendProbe


def test_explicit_backend_is_returned_unchanged() -> None:
    probe = SandboxBackendProbe()
    assert probe.resolve(SandboxBackend.DOCKER) is SandboxBackend.DOCKER
    assert probe.resolve(SandboxBackend.SUBPROCESS) is SandboxBackend.SUBPROCESS


def test_auto_falls_back_to_subprocess_when_docker_binary_missing() -> None:
    probe = SandboxBackendProbe()
    with patch("shutil.which", return_value=None):
        assert probe.resolve(SandboxBackend.AUTO) is SandboxBackend.SUBPROCESS


def test_auto_falls_back_to_subprocess_when_docker_daemon_unreachable() -> None:
    probe = SandboxBackendProbe()
    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", side_effect=OSError("no daemon")),
    ):
        assert probe.resolve(SandboxBackend.AUTO) is SandboxBackend.SUBPROCESS


def test_auto_resolves_to_docker_when_daemon_reachable() -> None:
    probe = SandboxBackendProbe()

    class _FakeResult:
        returncode = 0

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=_FakeResult()),
    ):
        assert probe.resolve(SandboxBackend.AUTO) is SandboxBackend.DOCKER


def test_auto_never_returns_auto() -> None:
    probe = SandboxBackendProbe()
    with patch("shutil.which", return_value=None):
        result = probe.resolve(SandboxBackend.AUTO)
    assert result is not SandboxBackend.AUTO
