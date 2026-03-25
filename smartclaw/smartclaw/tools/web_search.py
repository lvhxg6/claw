"""WebSearchTool — Tavily-powered web search.

Reads ``TAVILY_API_KEY`` from environment and returns formatted search results.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field
from tavily import TavilyClient

from smartclaw.tools.base import SmartClawTool

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Maximum number of results")


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class WebSearchTool(SmartClawTool):
    """Search the web using the Tavily API."""

    name: str = "web_search"
    description: str = "Search the web for information using Tavily."
    args_schema: type[BaseModel] = WebSearchInput

    async def _arun(self, query: str, max_results: int = 5, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            api_key = os.environ.get("TAVILY_API_KEY")
            if not api_key:
                return "Error: TAVILY_API_KEY environment variable is not set"

            try:
                client = TavilyClient(api_key=api_key)
                response = client.search(query=query, max_results=max_results)
            except Exception as e:
                return f"Error: Search failed — {e}"

            results = response.get("results", [])
            if not results:
                return "No results found."

            blocks: list[str] = []
            for r in results:
                title = r.get("title", "No title")
                url = r.get("url", "No URL")
                content = r.get("content", "No content")
                blocks.append(f"Title: {title}\nURL: {url}\nSnippet: {content}")

            return "\n\n---\n\n".join(blocks)

        return await self._safe_run(_do())
