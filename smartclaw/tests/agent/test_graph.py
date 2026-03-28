"""Unit tests for agent graph (build_graph, invoke, streaming)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from smartclaw.agent.graph import build_graph, invoke
from smartclaw.providers.config import ModelConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def _default_model_config() -> ModelConfig:
    return ModelConfig(
        primary="openai/gpt-4o",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


# ---------------------------------------------------------------------------
# build_graph tests (Requirement 7.1, 7.5)
# ---------------------------------------------------------------------------


class TestBuildGraph:
    """Test build_graph API."""

    def test_returns_compiled_graph(self) -> None:
        config = _default_model_config()
        graph = build_graph(config, tools=[add_numbers])
        assert graph is not None

    def test_accepts_empty_tools(self) -> None:
        config = _default_model_config()
        graph = build_graph(config, tools=[])
        assert graph is not None

    def test_accepts_stream_callback(self) -> None:
        config = _default_model_config()
        callback = MagicMock()
        graph = build_graph(config, tools=[], stream_callback=callback)
        assert graph is not None


# ---------------------------------------------------------------------------
# invoke tests (Requirement 7.2, 7.3)
# ---------------------------------------------------------------------------


class TestInvoke:
    """Test invoke API with mocked LLM."""

    @pytest.mark.asyncio
    async def test_invoke_returns_agent_state(self) -> None:
        """invoke returns a dict with AgentState keys."""
        config = _default_model_config()

        # Mock the FallbackChain.execute to return a simple AIMessage
        ai_response = AIMessage(content="Hello from the agent!")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_graph(config, tools=[])
            result = await invoke(graph, "Hi there")

        assert "messages" in result
        assert "iteration" in result
        assert result["iteration"] >= 1

    @pytest.mark.asyncio
    async def test_invoke_initializes_with_human_message(self) -> None:
        """invoke starts with a HumanMessage containing the user text."""
        config = _default_model_config()
        ai_response = AIMessage(content="Response")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_graph(config, tools=[])
            result = await invoke(graph, "Test message")

        # First message should be the user's HumanMessage
        first_msg = result["messages"][0]
        assert isinstance(first_msg, HumanMessage)
        assert first_msg.content == "Test message"

    @pytest.mark.asyncio
    async def test_invoke_respects_max_iterations(self) -> None:
        """invoke uses the provided max_iterations."""
        config = _default_model_config()
        ai_response = AIMessage(content="Done")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_graph(config, tools=[])
            result = await invoke(graph, "Hi", max_iterations=5)

        # Should have completed within max_iterations
        assert result["iteration"] <= 5

    @pytest.mark.asyncio
    async def test_invoke_passes_recursion_limit_to_langgraph(self) -> None:
        """invoke aligns LangGraph recursion_limit with max_iterations."""
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "messages": [HumanMessage(content="Hi"), AIMessage(content="Done")],
                "iteration": 1,
                "max_iterations": 5,
                "final_answer": "Done",
                "error": None,
                "session_key": None,
                "summary": None,
                "sub_agent_depth": None,
            }
        )

        await invoke(mock_graph, "Hi", max_iterations=5)

        mock_graph.ainvoke.assert_called_once()
        _, call_kwargs = mock_graph.ainvoke.call_args
        assert call_kwargs == {}
        call_args = mock_graph.ainvoke.call_args.args
        assert call_args[1]["recursion_limit"] == 25


# ---------------------------------------------------------------------------
# Non-streaming return (Requirement 4.4)
# ---------------------------------------------------------------------------


class TestNonStreaming:
    """Test non-streaming response."""

    @pytest.mark.asyncio
    async def test_returns_complete_response(self) -> None:
        config = _default_model_config()
        ai_response = AIMessage(content="Complete response text")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_graph(config, tools=[])
            result = await invoke(graph, "Give me a response")

        # Should have the final answer
        assert result.get("final_answer") == "Complete response text"
