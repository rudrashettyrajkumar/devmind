"""`CommandAllowlist` — SI-8 enforcement.

A sandboxed command may only invoke a binary whose basename is in
`ALLOWED_COMMAND_BINARIES`. The check is on `Path(argv[0]).name`, so `/usr/bin/python`
and `python` are the same decision and `./evil` is rejected.

Defence-in-depth (nothing here ever runs through a shell, so these are belt, not
braces): `argv[0]` may not contain a shell metacharacter (a real binary name never
does), and no argv entry may contain a NUL (the C string terminator — never a valid
argument byte). A `;`, `|`, or newline in a *later* argument is fine — a multi-line
`python -c "a; b()"` payload is a normal command.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from devmind.core.constants import (
    ALLOWED_COMMAND_BINARIES,
    FORBIDDEN_ARG_CHARACTERS,
    SHELL_METACHARACTERS,
)
from devmind.exceptions import SandboxError


class CommandAllowlist:
    """Validates an argv against the binary allowlist before anything runs."""

    def __init__(self, allowed: frozenset[str] = ALLOWED_COMMAND_BINARIES) -> None:
        self._allowed = allowed

    def validate(self, argv: Sequence[str]) -> None:
        """Raise `SandboxError` if `argv` is empty, its binary is outside the
        allowlist or malformed, or any entry carries a NUL byte.
        """
        if not argv:
            raise SandboxError("empty argv", details={"argv": list(argv)})

        if SHELL_METACHARACTERS & set(argv[0]):
            raise SandboxError(
                f"argv[0] {argv[0]!r} contains a shell metacharacter",
                details={"argv": list(argv)},
            )

        binary = PurePosixPath(argv[0]).name
        if binary not in self._allowed:
            raise SandboxError(
                f"binary {binary!r} is not on the sandbox allowlist",
                details={"binary": binary, "allowed": sorted(self._allowed)},
            )

        for index, token in enumerate(argv):
            bad = FORBIDDEN_ARG_CHARACTERS & set(token)
            if bad:
                raise SandboxError(
                    f"argv[{index}] contains a forbidden control character",
                    details={"argv": list(argv), "index": index},
                )
