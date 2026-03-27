"""AskClarificationTool — allows the Agent to ask the user for clarification.

When the LLM determines that it lacks sufficient information to complete a
task, it can invoke this tool to pose a clarifying question (with optional
predefined choices) to the user.  The actual interruption logic lives in
``action_node``, which intercepts the tool call and writes the request into
``AgentState.clarification_request`` instead of executing the tool body.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class AskClarificationInput(BaseModel):
    """Input schema for the ask_clarification tool."""

    question: str = Field(description="向用户提出的澄清问题")
    options: list[str] | None = Field(
        default=None,
        description="可选的预定义选项列表，供用户选择",
    )


class AskClarificationTool(BaseTool):
    """Ask the user a clarifying question when information is insufficient.

    This tool is intercepted by ``action_node`` at runtime — the ``_arun``
    method only returns a placeholder string and is never expected to
    execute real logic.
    """

    name: str = "ask_clarification"
    description: str = (
        "当信息不足以完成任务时，向用户提出澄清问题。"
        "可提供预定义选项供用户快速选择。"
    )
    args_schema: type[BaseModel] = AskClarificationInput

    def _run(self, **kwargs: Any) -> str:  # noqa: D401
        raise NotImplementedError("Use async _arun")

    async def _arun(  # type: ignore[override]
        self,
        question: str,
        options: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        # Actual logic is intercepted by action_node; this is a placeholder.
        return f"Clarification requested: {question}"
