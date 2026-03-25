"""Unit tests for WebSearchTool."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

from smartclaw.tools.web_search import WebSearchTool


class TestDefaultMaxResults:
    def test_default_max_results(self) -> None:
        from smartclaw.tools.web_search import WebSearchInput
        schema = WebSearchInput(query="test")
        assert schema.max_results == 5


class TestProviderFallback:
    async def test_tavily_used_when_key_set(self) -> None:
        tool = WebSearchTool()
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "Tavily Result", "url": "http://x", "content": "C"}]
        }
        env = dict(os.environ)
        env["TAVILY_API_KEY"] = "test-key"
        env.pop("BRAVE_API_KEY", None)

        with patch.dict(os.environ, env, clear=True), \
             patch("tavily.TavilyClient", return_value=mock_client):
            result = await tool._arun(query="test")
            assert "Tavily Result" in result

    async def test_no_keys_falls_back_to_duckduckgo(self) -> None:
        tool = WebSearchTool()
        env = dict(os.environ)
        env.pop("TAVILY_API_KEY", None)
        env.pop("BRAVE_API_KEY", None)

        async def mock_ddg(query: str, max_results: int) -> str:
            return "Title: DDG Result\nURL: http://ddg\nSnippet: test"

        import smartclaw.tools.web_search as ws
        original_providers = ws._PROVIDERS
        ws._PROVIDERS = [("DuckDuckGo", mock_ddg)]
        try:
            with patch.dict(os.environ, env, clear=True):
                result = await tool._arun(query="python programming")
                assert "DDG Result" in result
        finally:
            ws._PROVIDERS = original_providers


class TestBraveSearch:
    async def test_brave_used_when_key_set(self) -> None:
        tool = WebSearchTool()

        brave_json = {
            "web": {"results": [{"title": "Brave Result", "url": "http://b", "description": "desc"}]}
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = brave_json
        mock_resp.raise_for_status = MagicMock()

        # We need to mock httpx.AsyncClient as a context manager
        async def mock_get(*args: object, **kwargs: object) -> MagicMock:
            return mock_resp

        env = dict(os.environ)
        env["BRAVE_API_KEY"] = "brave-key"
        env.pop("TAVILY_API_KEY", None)

        with patch.dict(os.environ, env, clear=True), \
             patch("smartclaw.tools.web_search.httpx.AsyncClient") as mock_cls:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = mock_get
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool._arun(query="test")
            assert "Brave Result" in result
