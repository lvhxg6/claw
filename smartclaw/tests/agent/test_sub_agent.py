"""Unit tests for SubAgent module (Task 9.7).

Tests:
- Timeout cancels execution and returns error (Req 9.5)
- Invalid config (missing task/model) raises ValueError
- Concurrency timeout returns error (Req 10.3)
- Exception caught and returned as error string (Req 9.11)
- EphemeralStore doesn't pollute parent memory (Req 9.12)

Requirements: 9.5, 9.11, 9.12, 10.3
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.sub_agent import (
    ConcurrencyTimeoutError,
    DepthLimitExceededError,
    EphemeralStore,
    SpawnSubAgentTool,
    SubAgentConfig,
    spawn_sub_agent,
)


# ---------------------------------------------------------------------------
# Test: Timeout cancels execution (Req 9.5)
# ---------------------------------------------------------------------------


class TestTimeout:
    """Sub-agent timeout cancels execution and returns error string."""

    @pytest.mark.asyncio
    async def test_timeout_returns_error_string(self) -> None:
        """When sub-agent exceeds timeout_seconds, returns timeout error."""
        mock_graph = MagicMock()

        async def slow_invoke(graph, msg, **kwargs):
            await asyncio.sleep(10)  # Will be cancelled by timeout
            return {"final_answer": "Should not reach", "messages": [], "iteration": 1}

        config = SubAgentConfig(
            task="Slow task",
            model="openai/gpt-4o",
            timeout_seconds=1,  # 1 second timeout
        )

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=slow_invoke),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" in result
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_with_very_short_duration(self) -> None:
        """Even very short timeouts are handled gracefully."""
        mock_graph = MagicMock()

        async def slow_invoke(graph, msg, **kwargs):
            await asyncio.sleep(5)
            return {"final_answer": "Never", "messages": [], "iteration": 1}

        config = SubAgentConfig(
            task="Quick timeout task",
            model="openai/gpt-4o",
            timeout_seconds=0,  # Immediate timeout
        )

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=slow_invoke),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" in result


# ---------------------------------------------------------------------------
# Test: Invalid config raises ValueError
# ---------------------------------------------------------------------------


class TestInvalidConfig:
    """SubAgentConfig with missing task/model raises ValueError."""

    @pytest.mark.asyncio
    async def test_empty_task_raises_value_error(self) -> None:
        """Empty task string raises ValueError."""
        config = SubAgentConfig(task="", model="openai/gpt-4o")
        with pytest.raises(ValueError, match="task"):
            await spawn_sub_agent(config, parent_depth=0)

    @pytest.mark.asyncio
    async def test_whitespace_task_raises_value_error(self) -> None:
        """Whitespace-only task string raises ValueError."""
        config = SubAgentConfig(task="   ", model="openai/gpt-4o")
        with pytest.raises(ValueError, match="task"):
            await spawn_sub_agent(config, parent_depth=0)

    @pytest.mark.asyncio
    async def test_empty_model_raises_value_error(self) -> None:
        """Empty model string raises ValueError."""
        config = SubAgentConfig(task="Valid task", model="")
        with pytest.raises(ValueError, match="model"):
            await spawn_sub_agent(config, parent_depth=0)

    @pytest.mark.asyncio
    async def test_whitespace_model_raises_value_error(self) -> None:
        """Whitespace-only model string raises ValueError."""
        config = SubAgentConfig(task="Valid task", model="   ")
        with pytest.raises(ValueError, match="model"):
            await spawn_sub_agent(config, parent_depth=0)


# ---------------------------------------------------------------------------
# Test: Concurrency timeout returns error (Req 10.3)
# ---------------------------------------------------------------------------


class TestConcurrencyTimeout:
    """When concurrency wait timeout is exceeded, raises ConcurrencyTimeoutError."""

    @pytest.mark.asyncio
    async def test_concurrency_timeout_raises_error(self) -> None:
        """When semaphore is fully acquired and timeout expires, raises ConcurrencyTimeoutError."""
        semaphore = asyncio.Semaphore(1)
        # Acquire the only slot
        await semaphore.acquire()

        config = SubAgentConfig(
            task="Blocked task",
            model="openai/gpt-4o",
        )

        with pytest.raises(ConcurrencyTimeoutError):
            await spawn_sub_agent(
                config,
                parent_depth=0,
                semaphore=semaphore,
                concurrency_timeout=0.1,  # Very short timeout
            )

        # Release the slot we acquired
        semaphore.release()

    @pytest.mark.asyncio
    async def test_concurrency_succeeds_when_slot_available(self) -> None:
        """When semaphore has available slots, spawn proceeds normally."""
        semaphore = asyncio.Semaphore(2)
        mock_graph = MagicMock()

        async def mock_invoke(graph, msg, **kwargs):
            return {"final_answer": "Success", "messages": [], "iteration": 1}

        config = SubAgentConfig(
            task="Normal task",
            model="openai/gpt-4o",
        )

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
        ):
            result = await spawn_sub_agent(
                config,
                parent_depth=0,
                semaphore=semaphore,
                concurrency_timeout=5.0,
            )

        assert result == "Success"



# ---------------------------------------------------------------------------
# Test: Exception caught and returned as error string (Req 9.11)
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """Exceptions during sub-agent execution are caught and returned as error strings."""

    @pytest.mark.asyncio
    async def test_build_graph_exception_returns_error(self) -> None:
        """When build_graph raises, error is caught and returned as string."""
        config = SubAgentConfig(
            task="Failing task",
            model="openai/gpt-4o",
        )

        with patch(
            "smartclaw.agent.graph.build_graph",
            side_effect=RuntimeError("Graph build failed"),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" in result
        assert "Graph build failed" in result

    @pytest.mark.asyncio
    async def test_invoke_exception_returns_error(self) -> None:
        """When invoke raises, error is caught and returned as string."""
        mock_graph = MagicMock()
        config = SubAgentConfig(
            task="Invoke fail task",
            model="openai/gpt-4o",
        )

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch(
                "smartclaw.agent.graph.invoke",
                side_effect=RuntimeError("LLM connection failed"),
            ),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" in result
        assert "LLM connection failed" in result

    @pytest.mark.asyncio
    async def test_invoke_returns_error_state(self) -> None:
        """When invoke returns state with error field, error is returned."""
        mock_graph = MagicMock()
        config = SubAgentConfig(
            task="Error state task",
            model="openai/gpt-4o",
        )

        async def mock_invoke(graph, msg, **kwargs):
            return {
                "final_answer": None,
                "error": "Internal agent error",
                "messages": [],
                "iteration": 5,
            }

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" in result
        assert "Internal agent error" in result

    @pytest.mark.asyncio
    async def test_no_final_answer_no_error(self) -> None:
        """When invoke returns neither final_answer nor error, returns default message."""
        mock_graph = MagicMock()
        config = SubAgentConfig(
            task="No answer task",
            model="openai/gpt-4o",
        )

        async def mock_invoke(graph, msg, **kwargs):
            return {
                "final_answer": None,
                "error": None,
                "messages": [],
                "iteration": 25,
            }

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert "without producing a final answer" in result


# ---------------------------------------------------------------------------
# Test: EphemeralStore doesn't pollute parent memory (Req 9.12)
# ---------------------------------------------------------------------------


class TestEphemeralStoreIsolation:
    """EphemeralStore is isolated and doesn't pollute parent agent memory."""

    def test_ephemeral_store_is_independent(self) -> None:
        """Two EphemeralStore instances don't share state."""
        store_a = EphemeralStore(max_size=10)
        store_b = EphemeralStore(max_size=10)

        store_a.add_message(HumanMessage(content="Message A"))
        store_b.add_message(HumanMessage(content="Message B"))

        assert len(store_a.get_history()) == 1
        assert len(store_b.get_history()) == 1
        assert store_a.get_history()[0].content == "Message A"
        assert store_b.get_history()[0].content == "Message B"

    def test_ephemeral_store_get_history_returns_copy(self) -> None:
        """get_history returns a copy, not a reference to internal list."""
        store = EphemeralStore(max_size=10)
        store.add_message(HumanMessage(content="Original"))

        history = store.get_history()
        history.append(HumanMessage(content="Injected"))

        # Internal state should not be affected
        assert len(store.get_history()) == 1

    def test_ephemeral_store_truncate(self) -> None:
        """truncate keeps only the last N messages."""
        store = EphemeralStore(max_size=20)
        for i in range(10):
            store.add_message(HumanMessage(content=f"msg-{i}"))

        store.truncate(3)
        history = store.get_history()
        assert len(history) == 3
        assert history[0].content == "msg-7"
        assert history[1].content == "msg-8"
        assert history[2].content == "msg-9"

    def test_ephemeral_store_truncate_zero_clears(self) -> None:
        """truncate(0) clears all messages."""
        store = EphemeralStore(max_size=20)
        for i in range(5):
            store.add_message(HumanMessage(content=f"msg-{i}"))

        store.truncate(0)
        assert len(store.get_history()) == 0

    def test_ephemeral_store_auto_truncation(self) -> None:
        """Adding messages beyond max_size auto-truncates to max_size."""
        store = EphemeralStore(max_size=5)
        for i in range(10):
            store.add_message(HumanMessage(content=f"msg-{i}"))

        history = store.get_history()
        assert len(history) == 5
        # Should keep the last 5
        assert history[0].content == "msg-5"
        assert history[4].content == "msg-9"

    @pytest.mark.asyncio
    async def test_sub_agent_does_not_persist_to_parent_store(self) -> None:
        """Sub-agent execution uses ephemeral store, not parent's persistent store."""
        # The parent's memory store should not be called by spawn_sub_agent
        mock_graph = MagicMock()

        async def mock_invoke(graph, msg, **kwargs):
            # Verify no memory_store or session_key is passed
            assert kwargs.get("session_key") is None
            assert kwargs.get("memory_store") is None
            return {"final_answer": "Sub-agent done", "messages": [], "iteration": 1}

        config = SubAgentConfig(
            task="Isolated task",
            model="openai/gpt-4o",
        )

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
        ):
            result = await spawn_sub_agent(config, parent_depth=0)

        assert result == "Sub-agent done"


# ---------------------------------------------------------------------------
# Test: SpawnSubAgentTool
# ---------------------------------------------------------------------------


class TestSpawnSubAgentTool:
    """Tests for the SpawnSubAgentTool LangChain BaseTool."""

    def test_tool_name_and_description(self) -> None:
        """Tool has correct name and description."""
        tool = SpawnSubAgentTool()
        assert tool.name == "spawn_sub_agent"
        assert "subtask" in tool.description.lower() or "sub-agent" in tool.description.lower()

    def test_run_raises_not_implemented(self) -> None:
        """_run raises NotImplementedError."""
        tool = SpawnSubAgentTool()
        with pytest.raises(NotImplementedError):
            tool._run(task="test", model="openai/gpt-4o")

    @pytest.mark.asyncio
    async def test_arun_delegates_to_spawn(self) -> None:
        """_arun calls spawn_sub_agent and returns result."""
        mock_graph = MagicMock()

        async def mock_invoke(graph, msg, **kwargs):
            return {"final_answer": "Tool result", "messages": [], "iteration": 1}

        tool = SpawnSubAgentTool(default_model="openai/gpt-4o")

        with (
            patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
            patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
        ):
            result = await tool._arun(task="Do something")

        assert result == "Tool result"

    @pytest.mark.asyncio
    async def test_arun_depth_limit_returns_error(self) -> None:
        """_arun returns error string when depth limit is exceeded."""
        tool = SpawnSubAgentTool(
            default_model="openai/gpt-4o",
            parent_depth=5,
            max_depth=3,
        )

        result = await tool._arun(task="Deep task")
        assert "Error" in result
        assert "depth" in result.lower()
