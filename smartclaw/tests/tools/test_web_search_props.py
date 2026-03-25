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

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_title = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())
_url = st.from_regex(r"https://[a-z]{3,10}\.[a-z]{2,4}/[a-z]{1,10}", fullmatch=True)
_snippet = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

_search_result = st.fixed_dictionaries({
    "title": _title,
    "url": _url,
    "content": _snippet,
})

_results_list = st.lists(_search_result, min_size=1, max_size=5)


# ---------------------------------------------------------------------------
# Property 15: Web search result formatting
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 15: Web search result formatting
@given(results=_results_list)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_search_result_formatting(results: list[dict[str, str]]) -> None:
    """For any list of search results with title, URL, and content snippet,
    the formatted output contains all three fields for every result.

    **Validates: Requirements 5.6**
    """
    tool = WebSearchTool()

    mock_client = MagicMock()
    mock_client.search.return_value = {"results": results}

    with (
        patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}),
        patch("smartclaw.tools.web_search.TavilyClient", return_value=mock_client),
    ):
        output = await tool._arun(query="test")

    for r in results:
        assert r["title"] in output
        assert r["url"] in output
        assert r["content"] in output


# ---------------------------------------------------------------------------
# Property 16: Web search API error passthrough
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 16: Web search API error passthrough
@given(error_msg=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_api_error_passthrough(error_msg: str) -> None:
    """For any API error message from Tavily client, WebSearchTool returns
    a string containing that error message.

    **Validates: Requirements 5.5**
    """
    tool = WebSearchTool()

    mock_client = MagicMock()
    mock_client.search.side_effect = Exception(error_msg)

    with (
        patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}),
        patch("smartclaw.tools.web_search.TavilyClient", return_value=mock_client),
    ):
        output = await tool._arun(query="test")

    assert error_msg in output
