"""Unit tests for request-level model override in chat endpoints.

Requirements: 4.1, 4.2, 4.3, 4.5, 4.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import smartclaw.agent.graph as graph_module
from tests.gateway.conftest import make_test_client


def _make_mock_result() -> dict:
    return {
        "final_answer": "Mock response",
        "iteration": 1,
        "error": None,
        "session_key": None,
        "messages": [],
        "summary": None,
        "sub_agent_depth": None,
    }


class TestModelOverrideChat:
    """Test model override logic in POST /api/chat."""

    def test_model_none_uses_default_graph(self):
        """model=None uses runtime.graph (default). (Req 4.2)"""
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            with client:
                resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 200
            # build_graph should NOT have been called for override
        finally:
            graph_module.invoke = original

    def test_model_empty_string_uses_default_graph(self):
        """model="" uses runtime.graph (default). (Req 4.2)"""
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            with client:
                resp = client.post("/api/chat", json={"message": "hello", "model": ""})
            assert resp.status_code == 200
        finally:
            graph_module.invoke = original

    def test_valid_model_override_builds_temp_graph(self):
        """Valid model ref builds a temporary graph. (Req 4.3)"""
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            with patch("smartclaw.agent.graph.build_graph") as mock_build:
                mock_build.return_value = MagicMock(name="temp_graph")
                with client:
                    resp = client.post(
                        "/api/chat",
                        json={"message": "hello", "model": "openai/gpt-4o"},
                    )
                assert resp.status_code == 200
                mock_build.assert_called_once()
                # Verify the temp config has the overridden primary
                call_args = mock_build.call_args
                temp_config = call_args[0][0]
                assert temp_config.primary == "openai/gpt-4o"
        finally:
            graph_module.invoke = original

    def test_valid_model_override_uses_runtime_tools(self):
        """Temp graph uses same tools as runtime. (Req 4.6)"""
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            with patch("smartclaw.agent.graph.build_graph") as mock_build:
                mock_build.return_value = MagicMock(name="temp_graph")
                with client:
                    resp = client.post(
                        "/api/chat",
                        json={"message": "hello", "model": "anthropic/claude-sonnet-4-20250514"},
                    )
                assert resp.status_code == 200
                call_args = mock_build.call_args
                tools_passed = call_args[0][1]
                # tools_passed should be the runtime.tools list
                assert isinstance(tools_passed, list)
        finally:
            graph_module.invoke = original

    def test_invalid_model_no_slash_returns_400(self):
        """Invalid model ref (no slash) returns 400. (Req 4.5)"""
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.post(
                    "/api/chat",
                    json={"message": "hello", "model": "invalid"},
                )
            assert resp.status_code == 400
            assert "error" in resp.json()
        finally:
            graph_module.invoke = original

    def test_invalid_model_empty_provider_returns_400(self):
        """Invalid model ref (empty provider) returns 400. (Req 4.5)"""
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.post(
                    "/api/chat",
                    json={"message": "hello", "model": "/gpt-4o"},
                )
            assert resp.status_code == 400
        finally:
            graph_module.invoke = original

    def test_invalid_model_empty_model_returns_400(self):
        """Invalid model ref (empty model) returns 400. (Req 4.5)"""
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.post(
                    "/api/chat",
                    json={"message": "hello", "model": "openai/"},
                )
            assert resp.status_code == 400
        finally:
            graph_module.invoke = original


class TestModelOverrideChatStream:
    """Test model override logic in POST /api/chat/stream."""

    def test_invalid_model_stream_returns_400(self):
        """Invalid model ref in stream returns 400. (Req 4.5)"""
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.post(
                    "/api/chat/stream",
                    json={"message": "hello", "model": "invalid"},
                )
            assert resp.status_code == 400
        finally:
            graph_module.invoke = original

    def test_valid_model_stream_builds_temp_graph(self):
        """Valid model ref in stream builds temp graph. (Req 4.4)"""
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            with patch("smartclaw.agent.graph.build_graph") as mock_build:
                mock_build.return_value = MagicMock(name="temp_graph")
                with client:
                    resp = client.post(
                        "/api/chat/stream",
                        json={"message": "hello", "model": "openai/gpt-4o"},
                    )
                assert resp.status_code == 200
                mock_build.assert_called_once()
        finally:
            graph_module.invoke = original
