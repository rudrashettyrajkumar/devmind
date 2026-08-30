"""`run_command`, `run_tests`, and `git_diff` — the sandbox-backed tools."""

from __future__ import annotations

import dataclasses

import pytest

from devmind.exceptions import SandboxError
from devmind.schemas.repo import RepoProfile
from devmind.schemas.sandbox import SandboxCommand
from devmind.schemas.tools import GitDiffInput, RunCommandInput, RunTestsInput
from devmind.tools.git_diff_tool import GitDiffTool
from devmind.tools.run_command_tool import RunCommandTool
from devmind.tools.run_tests_tool import RunTestsTool
from devmind.tools.tool_context import ToolContext
from tests.fakes.fake_sandbox import FakeSandbox, command_result


def _sandbox(ctx: ToolContext) -> FakeSandbox:
    assert isinstance(ctx.sandbox, FakeSandbox)
    return ctx.sandbox


async def test_run_command_reports_exit_and_streams(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=0, stdout="hi", stderr=""))
    result = await RunCommandTool().execute(
        RunCommandInput(argv=("python", "-c", "print('hi')")), tool_context
    )
    assert not result.is_error
    assert "exit code: 0" in result.content
    assert "hi" in result.content


async def test_run_command_nonzero_exit_is_error(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=1, stderr="nope"))
    result = await RunCommandTool().execute(RunCommandInput(argv=("pytest",)), tool_context)
    assert result.is_error
    assert result.metadata["exit_code"] == 1


async def test_run_command_disallowed_binary_is_error(tool_context: ToolContext) -> None:
    class _Rejecting(FakeSandbox):
        async def run(self, command: SandboxCommand):  # type: ignore[override]
            raise SandboxError("binary 'curl' is not on the sandbox allowlist")

    ctx = dataclasses.replace(tool_context, sandbox=_Rejecting())
    result = await RunCommandTool().execute(RunCommandInput(argv=("curl", "http://x")), ctx)
    assert result.is_error
    assert "allowlist" in result.content


async def test_run_tests_without_a_suite_is_error(tool_context: ToolContext) -> None:
    ctx = dataclasses.replace(
        tool_context, profile=RepoProfile(language="python", has_test_suite=False)
    )
    result = await RunTestsTool().execute(RunTestsInput(), ctx)
    assert result.is_error


async def test_run_tests_builds_pytest_argv(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=0, stdout="1 passed"))
    await RunTestsTool().execute(
        RunTestsInput(node_ids=("tests/test_a.py::test_x",), keyword="fast"), tool_context
    )
    argv = _sandbox(tool_context).commands[0].argv
    assert argv[:3] == ("python", "-m", "pytest")
    assert "-k" in argv and "fast" in argv
    assert "tests/test_a.py::test_x" in argv


async def test_git_diff_caps_output(
    tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=0, stdout="+" * 5000))
    monkeypatch.setattr("devmind.tools.git_diff_tool.MAX_DIFF_CHARS", 100)
    result = await GitDiffTool().execute(GitDiffInput(), tool_context)
    assert result.metadata["truncated"] is True
    assert "diff truncated" in result.content


async def test_git_diff_empty_is_not_an_error(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=0, stdout=""))
    result = await GitDiffTool().execute(GitDiffInput(), tool_context)
    assert not result.is_error
    assert result.content == "(no changes)"


async def test_git_diff_failure_surfaces_stderr(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(
        command_result(exit_code=128, stderr="fatal: not a git repository")
    )
    result = await GitDiffTool().execute(GitDiffInput(), tool_context)
    assert result.is_error
    assert "not a git repository" in result.content


async def test_git_diff_paths_are_guarded_and_made_relative(tool_context: ToolContext) -> None:
    _sandbox(tool_context).queue(command_result(exit_code=0, stdout="diff --git ..."))
    await GitDiffTool().execute(GitDiffInput(paths=("src/pkg/calc.py",)), tool_context)
    argv = _sandbox(tool_context).commands[0].argv
    assert argv == ("git", "diff", "--", "src/pkg/calc.py")
