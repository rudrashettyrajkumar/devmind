"""The production `CommandRunner`: `asyncio` subprocess execution, argv-only.

Runs trusted host binaries (`git`, `gh`, `rg`, `grep`) for the read-only ingestion
phase. Never `shell=True`. Every process starts its own session so a timeout kills
the whole group, not just the parent. The environment is the host's, with the
non-interactive git variables forced on so a private repo fails fast instead of
blocking on a credential prompt (SI-2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path

from devmind.core.constants import (
    COMMAND_NOT_FOUND_EXIT_CODE,
    COMMAND_RUNNER_DEFAULT_TIMEOUT_SECONDS,
    NON_INTERACTIVE_GIT_ENV,
)
from devmind.interfaces.command_runner import CommandRunner
from devmind.schemas.command import CommandOutput

logger = logging.getLogger(__name__)


class SubprocessCommandRunner(CommandRunner):
    """Runs one command via `asyncio.create_subprocess_exec` and captures its output."""

    def __init__(self, default_timeout: float = COMMAND_RUNNER_DEFAULT_TIMEOUT_SECONDS) -> None:
        self._default_timeout = default_timeout

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandOutput:
        args = tuple(argv)
        if not args:
            # A caller contract violation, not a domain error — plain ValueError, the
            # same shape Pydantic validators raise elsewhere in the codebase.
            raise ValueError("argv must not be empty")

        merged_env = self._environment(env)
        effective_timeout = timeout if timeout is not None else self._default_timeout

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd) if cwd is not None else None,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError:
            return CommandOutput(
                argv=args,
                exit_code=COMMAND_NOT_FOUND_EXIT_CODE,
                stderr=f"{args[0]}: command not found",
            )
        except OSError as exc:
            return CommandOutput(
                argv=args, exit_code=COMMAND_NOT_FOUND_EXIT_CODE, stderr=f"{args[0]}: {exc}"
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=effective_timeout
            )
        except TimeoutError:
            self._kill_group(process)
            await process.wait()
            logger.warning("command timed out after %ss: %s", effective_timeout, args[0])
            return CommandOutput(
                argv=args,
                exit_code=-1,
                stderr=f"command timed out after {effective_timeout}s",
                timed_out=True,
            )

        return CommandOutput(
            argv=args,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _environment(overrides: Mapping[str, str] | None) -> dict[str, str]:
        # Deliberate: snapshot the parent process environment to pass to the child
        # (PATH, HOME, and the user's existing `gh`/`git` auth for read-only clones).
        # This is process-environment inheritance, not configuration access — no
        # DevMind setting is read here; those all live in core/config.py.
        env = dict(os.environ)
        env.update(NON_INTERACTIVE_GIT_ENV)
        if overrides:
            env.update(overrides)
        return env

    @staticmethod
    def _kill_group(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
