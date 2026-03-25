"""SmartClawTool — abstract base class for all non-browser tools.

Inherits from LangChain ``BaseTool`` and provides a unified ``_safe_run``
async wrapper that catches all exceptions and returns human-readable error
strings to the Agent Graph.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import structlog
from langchain_core.tools import BaseTool
from pydantic import BaseModel


class SmartClawTool(BaseTool):
    """Abstract base for all non-browser SmartClaw tools."""

    name: str
    description: str
    args_schema: type[BaseModel]

    def _run(self, **kwargs: Any) -> str:
        raise NotImplementedError("Use async")

    async def _safe_run(self, coro: Any) -> str:
        """Catch all exceptions, log via structlog, return error string."""
        try:
            result: str = await coro
            return result
        except Exception as e:
            logger = structlog.get_logger(component=f"tools.{self.name}")
            logger.error("tool_error", tool=self.name, error=str(e))
            return f"Error: {e}"

    @abstractmethod
    async def _arun(self, **kwargs: Any) -> str: ...
