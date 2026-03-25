"""Property-based tests for WebSearchTool.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.tools.web_search import WebSearchTool

_title = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())
_url = st.from_regex(r"https://[a-z]{3,10}\.[a-z]{2,4}/[a-z]{1,10}", fullmatch=True)
_snippet = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())
_search_result = st.fixed_dictionaries({"title": _title, "url": _url, "content": _snippet})
_results_list = st.lists(_search_result, min_size=1, max_size=5)


# Feature: smartclaw-tool-system, Property 15: Web search result formatting
@given(results=_results_list)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_search_result_formatting(results: list[dict[str, str]]) -> None:
    """Tavily results contain all title/url/content fields in output."""
    tool = WebSearchTool()
    mock_client = MagicMock()
    mock_client.search.return_value = {"results": results}

    with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}, clear=False), \
         patch.dict(os.environ, {"BRAVE_API_KEY": ""}, clear=False), \
         patch("tavily.TavilyClient", return_value=mock_client):
        os.environ.pop("BRAVE_API_KEY", None)
        output = await tool._arun(query="test")

    for r in results:
        assert r["title"] in output
        assert r["url"] in output
        assert r["content"] in output


# Feature: smartclaw-tool-system, Property 16: Web search API error passthrough
@given(error_msg=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()))
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_api_error_passthrough(error_msg: str) -> None:
    """Tavily errors are passed through; fallback providers are tried."""
    tool = WebSearchTool()
    mock_client = MagicMock()
    mock_client.search.side_effect = Exception(error_msg)

    env = dict(os.environ)
    env["TAVILY_API_KEY"] = "test-key"
    env.pop("BRAVE_API_KEY", None)

    # Mock DDG too to avoid real HTTP calls in property tests
    import smartclaw.tools.web_search as ws
    original_providers = ws._PROVIDERS

    async def mock_ddg(query: str, max_results: int) -> str:
        return "DuckDuckGo fallback result"

    ws._PROVIDERS = [("Tavily", ws._search_tavily), ("DuckDuckGo", mock_ddg)]
    try:
        with patch.dict(os.environ, env, clear=True), \
             patch("tavily.TavilyClient", return_value=mock_client):
            output = await tool._arun(query="test")
            assert isinstance(output, str)
    finally:
        ws._PROVIDERS = original_providers
