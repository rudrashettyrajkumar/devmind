from __future__ import annotations

import pytest

from devmind.exceptions import SandboxError
from devmind.services.command_allowlist import CommandAllowlist


@pytest.fixture
def allowlist() -> CommandAllowlist:
    return CommandAllowlist()


def test_allowed_bare_binary_passes(allowlist: CommandAllowlist) -> None:
    allowlist.validate(["pytest", "-q"])


def test_allowed_absolute_path_passes_on_basename(allowlist: CommandAllowlist) -> None:
    allowlist.validate(["/usr/bin/python", "-m", "pytest"])


def test_disallowed_binary_raises(allowlist: CommandAllowlist) -> None:
    with pytest.raises(SandboxError) as excinfo:
        allowlist.validate(["curl", "https://evil.example"])
    assert "not on the sandbox allowlist" in str(excinfo.value)


def test_relative_dot_slash_binary_is_rejected(allowlist: CommandAllowlist) -> None:
    with pytest.raises(SandboxError):
        allowlist.validate(["./evil"])


def test_empty_argv_raises(allowlist: CommandAllowlist) -> None:
    with pytest.raises(SandboxError):
        allowlist.validate([])


@pytest.mark.parametrize(
    "argv",
    [
        ["py;thon", "-c", "pass"],
        ["python|tee", "x"],
        ["python$(x)", "x"],
        ["python x", "y"],
    ],
)
def test_metacharacter_in_the_binary_is_rejected(
    allowlist: CommandAllowlist, argv: list[str]
) -> None:
    with pytest.raises(SandboxError) as excinfo:
        allowlist.validate(argv)
    assert "metacharacter" in str(excinfo.value)


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "import x; x.main()"],
        ["pytest", "-k", "a or b"],
        ["git", "log", "--format=%H"],
        ["pytest", "tests/pkg/test_x.py::test_y"],
    ],
)
def test_metacharacters_in_arguments_are_allowed(
    allowlist: CommandAllowlist, argv: list[str]
) -> None:
    allowlist.validate(argv)  # a ';' in a -c payload is not a shell operator here


def test_nul_byte_in_any_argument_is_rejected(allowlist: CommandAllowlist) -> None:
    with pytest.raises(SandboxError) as excinfo:
        allowlist.validate(["pytest", "x\x00y"])
    assert "control character" in str(excinfo.value)


def test_newline_in_an_argument_is_allowed(allowlist: CommandAllowlist) -> None:
    allowlist.validate(["python", "-c", "import x\nx.main()\n"])


def test_custom_allowlist_is_honoured() -> None:
    tight = CommandAllowlist(frozenset({"python"}))
    tight.validate(["python", "-V"])
    with pytest.raises(SandboxError):
        tight.validate(["pytest"])
