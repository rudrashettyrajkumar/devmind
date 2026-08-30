from __future__ import annotations

import pytest
from pydantic import ValidationError

from devmind.schemas.tools import FinishInput
from devmind.tools.finish_tool import FinishTool
from devmind.tools.tool_context import ToolContext


async def test_returns_summary_and_confidence(tool_context: ToolContext) -> None:
    result = await FinishTool().execute(
        FinishInput(summary="investigated the bug", confidence=0.8), tool_context
    )
    assert not result.is_error
    assert "investigated the bug" in result.content
    assert result.metadata["confidence"] == 0.8
    assert result.metadata["summary"] == "investigated the bug"


@pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
def test_confidence_out_of_range_is_rejected_by_the_schema(bad: float) -> None:
    with pytest.raises(ValidationError):
        FinishInput(summary="x", confidence=bad)


def test_empty_summary_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        FinishInput(summary="", confidence=0.5)
