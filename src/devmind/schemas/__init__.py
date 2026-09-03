"""Pydantic request/response DTOs. Every payload crossing a layer boundary is one of
these — never a raw dict (Claude.md §2).
"""

from devmind.schemas.agent import FinishSignal, LoopOutcome
from devmind.schemas.approval import (
    ApprovalRecord,
    ApprovalRequest,
    ChangeSummary,
    FileDiffStat,
    SessionMetrics,
    TestEvidence,
    TestRunSummary,
)
from devmind.schemas.command import CommandOutput
from devmind.schemas.event import EventRead
from devmind.schemas.github import IssueRead
from devmind.schemas.health import HealthRead
from devmind.schemas.llm import (
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResultBlock,
)
from devmind.schemas.prompt import LoadedPrompt, PromptMetadata
from devmind.schemas.pull_request import CommitMessage, DraftPullRequest, PullRequestRead
from devmind.schemas.repo import (
    FileTree,
    FileTreeNode,
    IngestionResult,
    ModuleSymbols,
    RepoBrief,
    RepoProfile,
    SearchHit,
    Symbol,
    SymbolIndex,
)
from devmind.schemas.sandbox import CommandResult, SandboxCommand
from devmind.schemas.session import SessionCreate, SessionRead, SessionSummary
from devmind.schemas.test_execution import (
    CorrectionDecision,
    TestFailure,
    TestFailureReport,
    TestRunResult,
)
from devmind.schemas.todo import TodoItemRead
from devmind.schemas.tools import TodoItemWrite, ToolResult

__all__ = [
    "ApprovalRecord",
    "ApprovalRequest",
    "ChangeSummary",
    "CommandOutput",
    "CommandResult",
    "CommitMessage",
    "CorrectionDecision",
    "DraftPullRequest",
    "EventRead",
    "FileDiffStat",
    "FileTree",
    "FileTreeNode",
    "FinishSignal",
    "HealthRead",
    "IngestionResult",
    "IssueRead",
    "LLMRequest",
    "LLMResponse",
    "LoadedPrompt",
    "LoopOutcome",
    "ModuleSymbols",
    "PromptMetadata",
    "PullRequestRead",
    "RepoBrief",
    "RepoProfile",
    "SandboxCommand",
    "SearchHit",
    "SessionCreate",
    "SessionMetrics",
    "SessionRead",
    "SessionSummary",
    "Symbol",
    "SymbolIndex",
    "TestEvidence",
    "TestFailure",
    "TestFailureReport",
    "TestRunResult",
    "TestRunSummary",
    "TodoItemRead",
    "TodoItemWrite",
    "TokenUsage",
    "ToolCall",
    "ToolResult",
    "ToolResultBlock",
]
