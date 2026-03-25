"""Unit tests for WebSearchTool."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from smartclaw.tools.web_search import WebSearchTool


class TestDefaultMaxResults:
    """Test default max_results=5 (Req 5.2)."""

    def test_default_max_results(self) -> None:
        from smartclaw.tools.web_search import WebSearchInput

        schema = WebSearchInput(query="test")
        assert schema.max_results == 5


class TestApiKeyFromEnv:
    """Test API key read from env TAVILY_API_KEY (Req 5.3)."""

    @pytest.mark.asyncio
    async def test_reads_api_key_from_env(self) -> None:
        tool = WebSearchTool()

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "T", "url": "http://x", "content": "C"}]
        }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}), \
             patch("smartclaw.tools.web_search.TavilyClient", return_value=mock_client) as mock_cls:
            await tool._arun(query="test")
            mock_cls.assert_called_once_with(api_key="test-key")


class TestMissingApiKey:
    """Test missing API key returns specific error string (Req 5.4)."""

    @pytest.mark.asyncio
    async def test_missing_key_error(self) -> None:
        tool = WebSearchTool()

        with patch.dict(os.environ, {}, clear=True):
            # Ensure TAVILY_API_KEY is not set
            os.environ.pop("TAVILY_API_KEY", None)
            result = await tool._arun(query="test")
            assert result == "Error: TAVILY_API_KEY environment variable is not set"
