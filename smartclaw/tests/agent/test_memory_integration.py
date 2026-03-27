"""Integration tests for Memory-Agent integration (Task 4.3).

Tests the invoke() function's memory integration behavior:
- session_key=None operates identically to P0 (stateless)
- session_key provided loads history and summary (mock MemoryStore and AutoSummarizer)
- New messages are persisted after graph completes
- maybe_summarize is called after graph completes

Requirements: 4.1, 4.2, 4.3, 4.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from smartclaw.agent.graph import build_graph, invoke
from smartclaw.providers.config import ModelConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_model_config() -> ModelConfig:
    return ModelConfig(
        primary="openai/gpt-4o",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


def _mock_graph_invoke(ai_content: str = "Hello from agent!"):
    """Patch FallbackChain so build_graph + invoke returns a predictable AIMessage."""
    ai_response = AIMessage(content=ai_content)
    mock_fc_cls = patch("smartclaw.agent.graph.FallbackChain")
    return mock_fc_cls, ai_response


def _build_patched_graph(ai_content: str = "Hello from agent!"):
    """Build a graph with mocked LLM that returns a fixed response."""
    config = _default_model_config()
    ai_response = AIMessage(content=ai_content)

    patcher = patch("smartclaw.agent.graph.FallbackChain")
    mock_fc_cls = patcher.start()
    mock_fc = AsyncMock()
    mock_fc_cls.return_value = mock_fc
    mock_result = MagicMock()
    mock_result.response = ai_response
    mock_fc.execute = AsyncMock(return_value=mock_result)

    graph = build_graph(config, tools=[])
    return graph, patcher


# ---------------------------------------------------------------------------
# Test: session_key=None — stateless P0 behavior (Req 4.5)
# ---------------------------------------------------------------------------


class TestStatelessBehavior:
    """When session_key is None, invoke behaves identically to P0."""

    @pytest.mark.asyncio
    async def test_no_session_key_returns_agent_state(self) -> None:
        """invoke without session_key returns a valid AgentState."""
        graph, patcher = _build_patched_graph("Stateless response")
        try:
            result = await invoke(graph, "Hi there")
            assert "messages" in result
            assert "iteration" in result
            assert result["iteration"] >= 1
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_no_session_key_does_not_call_memory(self) -> None:
        """invoke without session_key never touches memory_store or summarizer."""
        graph, patcher = _build_patched_graph("Response")
        mock_store = AsyncMock()
        mock_summarizer = AsyncMock()
        try:
            await invoke(
                graph,
                "Hello",
                session_key=None,
                memory_store=mock_store,
                summarizer=mock_summarizer,
            )
            # memory_store methods should NOT be called
            mock_store.get_history.assert_not_called()
            mock_store.get_summary.assert_not_called()
            mock_store.add_full_message.assert_not_called()
            mock_summarizer.build_context.assert_not_called()
            mock_summarizer.maybe_summarize.assert_not_called()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_no_memory_store_with_session_key(self) -> None:
        """invoke with session_key but no memory_store stays stateless."""
        graph, patcher = _build_patched_graph("Response")
        try:
            # Should not raise — memory_store is None so memory path is skipped
            result = await invoke(graph, "Hello", session_key="test-session")
            assert "messages" in result
            assert result["iteration"] >= 1
        finally:
            patcher.stop()


# ---------------------------------------------------------------------------
# Test: session_key provided — loads history and summary (Req 4.1)
# ---------------------------------------------------------------------------


class TestMemoryLoading:
    """When session_key is provided with memory_store, history and summary are loaded."""

    @pytest.mark.asyncio
    async def test_loads_history_from_store(self) -> None:
        """invoke loads history from memory_store.get_history when session_key is set."""
        graph, patcher = _build_patched_graph("Agent reply")
        mock_store = AsyncMock()
        prior_history = [HumanMessage(content="Previous question")]
        mock_store.get_history = AsyncMock(return_value=prior_history)

        try:
            result = await invoke(
                graph,
                "New question",
                session_key="sess-1",
                memory_store=mock_store,
            )
            mock_store.get_history.assert_called_once_with("sess-1")
            # Messages should include the prior history + new user message
            msgs = result["messages"]
            contents = [m.content for m in msgs if isinstance(m, HumanMessage)]
            assert "Previous question" in contents
            assert "New question" in contents
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_builds_context_with_summarizer(self) -> None:
        """invoke calls summarizer.build_context when summarizer is provided."""
        graph, patcher = _build_patched_graph("Agent reply")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[])

        mock_summarizer = AsyncMock()
        # build_context returns messages with summary prepended
        summary_msg = SystemMessage(content="Previous conversation summary:\nSome summary")

        async def fake_build_context(session_key, messages, system_prompt=None):
            return [summary_msg] + messages

        mock_summarizer.build_context = AsyncMock(side_effect=fake_build_context)
        mock_summarizer.maybe_summarize = AsyncMock(return_value=[])

        try:
            await invoke(
                graph,
                "Hello",
                session_key="sess-2",
                memory_store=mock_store,
                summarizer=mock_summarizer,
            )
            mock_summarizer.build_context.assert_called_once()
            call_args = mock_summarizer.build_context.call_args
            assert call_args[0][0] == "sess-2"  # session_key
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_empty_history_still_works(self) -> None:
        """invoke works when memory_store returns empty history."""
        graph, patcher = _build_patched_graph("Response")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[])

        try:
            result = await invoke(
                graph,
                "First message",
                session_key="new-session",
                memory_store=mock_store,
            )
            assert result["iteration"] >= 1
            mock_store.get_history.assert_called_once_with("new-session")
        finally:
            patcher.stop()


# ---------------------------------------------------------------------------
# Test: messages persisted after graph completes (Req 4.2)
# ---------------------------------------------------------------------------


class TestMessagePersistence:
    """New messages are persisted via add_full_message after graph completes."""

    @pytest.mark.asyncio
    async def test_persists_messages_after_completion(self) -> None:
        """invoke calls add_full_message for each result message."""
        graph, patcher = _build_patched_graph("Persisted response")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[])

        try:
            result = await invoke(
                graph,
                "Save this",
                session_key="persist-sess",
                memory_store=mock_store,
            )
            # add_full_message should be called for each message in the result
            result_msgs = result.get("messages", [])
            assert mock_store.add_full_message.call_count == len(result_msgs)
            # Each call should use the correct session_key
            for call in mock_store.add_full_message.call_args_list:
                assert call[0][0] == "persist-sess"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_no_persistence_without_session_key(self) -> None:
        """invoke does not persist messages when session_key is None."""
        graph, patcher = _build_patched_graph("No persist")
        mock_store = AsyncMock()

        try:
            await invoke(
                graph,
                "Ephemeral",
                session_key=None,
                memory_store=mock_store,
            )
            mock_store.add_full_message.assert_not_called()
        finally:
            patcher.stop()


# ---------------------------------------------------------------------------
# Test: maybe_summarize called after graph completes (Req 4.3)
# ---------------------------------------------------------------------------


class TestSummarizationTrigger:
    """maybe_summarize is called after graph completes when memory is enabled."""

    @pytest.mark.asyncio
    async def test_maybe_summarize_called(self) -> None:
        """invoke calls summarizer.maybe_summarize after graph completion."""
        graph, patcher = _build_patched_graph("Summarize check")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[])

        mock_summarizer = AsyncMock()
        mock_summarizer.build_context = AsyncMock(
            side_effect=lambda sk, msgs, **kw: msgs
        )
        mock_summarizer.maybe_summarize = AsyncMock(return_value=[])

        try:
            await invoke(
                graph,
                "Check summarize",
                session_key="summ-sess",
                memory_store=mock_store,
                summarizer=mock_summarizer,
            )
            mock_summarizer.maybe_summarize.assert_called_once()
            call_args = mock_summarizer.maybe_summarize.call_args
            assert call_args[0][0] == "summ-sess"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_maybe_summarize_not_called_without_summarizer(self) -> None:
        """invoke skips summarization when summarizer is None."""
        graph, patcher = _build_patched_graph("No summarizer")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[])

        try:
            # Should not raise even without summarizer
            await invoke(
                graph,
                "No summarize",
                session_key="no-summ",
                memory_store=mock_store,
                summarizer=None,
            )
            # No assertion on summarizer — it's None, so nothing to check
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_maybe_summarize_receives_updated_history(self) -> None:
        """maybe_summarize receives the full updated history from store."""
        graph, patcher = _build_patched_graph("Updated history")
        mock_store = AsyncMock()
        # Initial get_history returns empty, but after persistence
        # the second get_history call returns the updated history
        updated_msgs = [
            HumanMessage(content="Updated history"),
            AIMessage(content="Updated history"),
        ]
        mock_store.get_history = AsyncMock(
            side_effect=[[], updated_msgs]
        )

        mock_summarizer = AsyncMock()
        mock_summarizer.build_context = AsyncMock(
            side_effect=lambda sk, msgs, **kw: msgs
        )
        mock_summarizer.maybe_summarize = AsyncMock(return_value=updated_msgs)

        try:
            await invoke(
                graph,
                "Test updated",
                session_key="updated-sess",
                memory_store=mock_store,
                summarizer=mock_summarizer,
            )
            # maybe_summarize should receive the updated history
            call_args = mock_summarizer.maybe_summarize.call_args
            assert call_args[0][1] == updated_msgs
        finally:
            patcher.stop()


class TestContextEngineLifecycle:
    """ContextEngine lifecycle hooks are invoked by invoke()."""

    @pytest.mark.asyncio
    async def test_context_engine_bootstrap_and_after_turn_called(self) -> None:
        """invoke bootstraps context engine and runs after_turn on completion."""
        graph, patcher = _build_patched_graph("Context engine response")
        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(side_effect=[[], []])
        mock_engine = AsyncMock()
        mock_engine.assemble = AsyncMock(side_effect=lambda msgs, **kw: msgs)
        mock_engine.after_turn = AsyncMock(return_value=[])

        try:
            await invoke(
                graph,
                "Hello context engine",
                session_key="ctx-sess",
                memory_store=mock_store,
                context_engine=mock_engine,
            )
            mock_engine.bootstrap.assert_awaited_once_with("ctx-sess", system_prompt=None)
            mock_engine.assemble.assert_awaited_once()
            mock_engine.after_turn.assert_awaited_once()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_session_hooks_emitted_when_session_key_present(self) -> None:
        """invoke emits session:start and session:end hooks for session-scoped runs."""
        graph, patcher = _build_patched_graph("Hook response")

        with patch("smartclaw.hooks.registry.trigger", new_callable=AsyncMock) as mock_trigger:
            try:
                await invoke(graph, "Hello hooks", session_key="hook-sess")
            finally:
                patcher.stop()

        hook_points = [call.args[0] for call in mock_trigger.await_args_list]
        assert "session:start" in hook_points
        assert "session:end" in hook_points
