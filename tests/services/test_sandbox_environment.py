from __future__ import annotations

import pytest

from devmind.core.constants import SANDBOX_FORBIDDEN_ENV_FRAGMENTS
from devmind.services.sandbox_environment import SandboxEnvironment


@pytest.fixture(autouse=True)
def _polluted_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/dev")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_real")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-real")
    monkeypatch.setenv("MY_DB_PASSWORD", "hunter2")


def test_only_allowlisted_host_vars_pass_through() -> None:
    env = SandboxEnvironment().build()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/dev"
    assert "MY_DB_PASSWORD" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_credential_vars_are_blanked_not_just_absent() -> None:
    env = SandboxEnvironment().build()
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["GITHUB_TOKEN"] == ""
    assert env["GH_TOKEN"] == ""


def test_git_is_made_non_interactive() -> None:
    env = SandboxEnvironment().build()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "/bin/false"


def test_no_forbidden_fragment_survives_with_a_real_value() -> None:
    env = SandboxEnvironment().build()
    for name, value in env.items():
        if any(fragment in name.upper() for fragment in SANDBOX_FORBIDDEN_ENV_FRAGMENTS):
            assert value == "", f"{name} leaked a non-empty value into the sandbox"


def test_extra_env_is_applied_but_cannot_unblank_a_scrubbed_credential() -> None:
    env = SandboxEnvironment().build({"PYTEST_MARKER": "1", "ANTHROPIC_API_KEY": "sneaky"})
    assert env["PYTEST_MARKER"] == "1"
    assert env["ANTHROPIC_API_KEY"] == ""
