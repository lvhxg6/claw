"""WebSearchTool — multi-provider web search.

Supports Tavily, Brave Search, and DuckDuckGo (free, no API key).
Provider selection priority: Brave > Tavily > DuckDuckGo.
Automatically selects the first provider with a configured API key,
falling back to DuckDuckGo (no key required).
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field

from smartclaw.tools.base import SmartClawTool

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Maximum number of results")


# ---------------------------------------------------------------------------
# Search providers
# ---------------------------------------------------------------------------

_SEARCH_TIMEOUT = 10


async def _search_brave(query: str, max_results: int) -> str:
    """Search via Brave Search API."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return ""  # signal: not available

    url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={max_results}"
    async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
        resp = await client.get(url, headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        })
        resp.raise_for_status()

    data = resp.json()
    results = data.get("web", {}).get("results", [])
    if not results:
        return "No results found."

    blocks: list[str] = []
    for r in results[:max_results]:
        title = r.get("title", "No title")
        link = r.get("url", "No URL")
        desc = r.get("description", "")
        blocks.append(f"Title: {title}\nURL: {link}\nSnippet: {desc}")
    return "\n\n---\n\n".join(blocks)


async def _search_tavily(query: str, max_results: int) -> str:
    """Search via Tavily API."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return ""  # signal: not available

    from tavily import TavilyClient
    client = TavilyClient(api_key=api_key)
    response = client.search(query=query, max_results=max_results)

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


# DuckDuckGo HTML scraping regexes
_RE_DDG_LINK = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>'
)
_RE_DDG_SNIPPET = re.compile(
    r'<a class="result__snippet[^"]*".*?>([\s\S]*?)</a>'
)
_RE_TAGS = re.compile(r"<[^>]+>")


async def _search_duckduckgo(query: str, max_results: int) -> str:
    """Search via DuckDuckGo HTML (no API key required)."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        resp.raise_for_status()

    html = resp.text
    links = _RE_DDG_LINK.findall(html)
    snippets = _RE_DDG_SNIPPET.findall(html)

    if not links:
        return "No results found."

    blocks: list[str] = []
    for i, (href, raw_title) in enumerate(links[:max_results]):
        title = _RE_TAGS.sub("", raw_title).strip()
        snippet = _RE_TAGS.sub("", snippets[i]).strip() if i < len(snippets) else ""
        blocks.append(f"Title: {title}\nURL: {href}\nSnippet: {snippet}")
    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

# Priority: Brave > Tavily > DuckDuckGo
_PROVIDERS = [
    ("Brave", _search_brave),
    ("Tavily", _search_tavily),
    ("DuckDuckGo", _search_duckduckgo),
]


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class WebSearchTool(SmartClawTool):
    """Search the web using Brave, Tavily, or DuckDuckGo (auto-selected by available API keys)."""

    name: str = "web_search"
    description: str = "Search the web for information. Supports Brave Search, Tavily, and DuckDuckGo."
    args_schema: type[BaseModel] = WebSearchInput

    async def _arun(self, query: str, max_results: int = 5, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            for provider_name, search_fn in _PROVIDERS:
                try:
                    result = await search_fn(query, max_results)
                    if result:  # empty string means provider not configured
                        return result
                except Exception as e:
                    # Try next provider
                    continue
            return "Error: No search provider available. Set BRAVE_API_KEY or TAVILY_API_KEY, or ensure DuckDuckGo is reachable."

        return await self._safe_run(_do())
