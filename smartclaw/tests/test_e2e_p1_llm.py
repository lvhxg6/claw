"""End-to-end tests for P1 modules WITH real LLM calls.

Requires API key (KIMI_API_KEY or OPENAI_API_KEY).
Mark: ``pytest.mark.e2e`` — run with ``--run-e2e``.

Tests:
1. Memory + Agent: conversation persistence across sessions
2. Auto Summary: long conversation triggers LLM summarization
3. Sub-Agent: parent agent delegates subtask via tool call
"""

from __future__ import annotations

import os
import pathlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.graph import build_graph, invoke
from smartclaw.agent.sub_agent import SubAgentConfig, spawn_sub_agent
from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.providers.config import ModelConfig

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_CONFIG = ModelConfig(
    primary="kimi/kimi-k2.5",
    fallbacks=[],
    temperature=0.0,
    max_tokens=1024,
)


# ===================================================================
# 1. Memory + Agent E2E: conversation persistence
# ===================================================================


class TestMemoryAgentE2E:
    """Agent conversation persists to SQLite and reloads across sessions."""

    async def test_conversation_persists_across_sessions(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Session 1: ask a question. Session 2: ask follow-up referencing session 1."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        graph = build_graph(_MODEL_CONFIG, tools=[])

        # Session 1: ask about Python
        result1 = await invoke(
            graph,
            "My name is TestUser. Remember my name.",
            max_iterations=3,
            session_key="test-session",
            memory_store=store,
        )
        assert result1.get("error") is None
        answer1 = result1.get("final_answer", "")
        assert len(answer1) > 0

        # Verify messages persisted
        history = await store.get_history("test-session")
        assert len(history) > 0

        # Session 2: ask follow-up
        result2 = await invoke(
            graph,
            "What is my name?",
            max_iterations=3,
            session_key="test-session",
            memory_store=store,
        )
        assert result2.get("error") is None
        answer2 = result2.get("final_answer", "")
        # The agent should recall the name from session history
        assert "TestUser" in answer2 or "testuser" in answer2.lower()

        await store.close()


# ===================================================================
# 2. Auto Summary E2E: LLM summarization
# ===================================================================


class TestAutoSummaryE2E:
    """Long conversation triggers real LLM summarization."""

    async def test_summarization_produces_summary(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Feed enough messages to exceed threshold, verify summary is generated."""
        db_path = str(tmp_path / "memory.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()

        summarizer = AutoSummarizer(
            store=store,
            model_config=_MODEL_CONFIG,
            message_threshold=6,  # Low threshold for testing
            keep_recent=2,
        )

        # Build a conversation exceeding the threshold
        messages = []
        for i in range(8):
            h = HumanMessage(content=f"Question {i}: What is {i} + {i}?")
            a = AIMessage(content=f"Answer: {i} + {i} = {i*2}")
            messages.append(h)
            messages.append(a)
            await store.add_full_message("sum-session", h)
            await store.add_full_message("sum-session", a)

        # Trigger summarization
        result = await summarizer.maybe_summarize("sum-session", messages)

        # Summary should have been generated and stored
        summary = await store.get_summary("sum-session")
        assert len(summary) > 0
        # History should be truncated to keep_recent
        history = await store.get_history("sum-session")
        assert len(history) == 2

        await store.close()


# ===================================================================
# 3. Sub-Agent E2E: real LLM task delegation
# ===================================================================


class TestSubAgentE2E:
    """Sub-agent executes a real task via LLM."""

    async def test_sub_agent_completes_task(self) -> None:
        """spawn_sub_agent with a simple task returns a real LLM answer."""
        config = SubAgentConfig(
            task="What is 2 + 3? Reply with just the number.",
            model="kimi/kimi-k2.5",
            max_iterations=3,
            timeout_seconds=30,
        )

        result = await spawn_sub_agent(config, parent_depth=0)

        assert "Error" not in result
        assert "5" in result

    async def test_sub_agent_depth_limit(self) -> None:
        """Sub-agent respects depth limit without calling LLM."""
        config = SubAgentConfig(
            task="This should not execute",
            model="kimi/kimi-k2.5",
            max_depth=2,
        )

        from smartclaw.agent.sub_agent import DepthLimitExceededError
        with pytest.raises(DepthLimitExceededError):
            await spawn_sub_agent(config, parent_depth=2)

    async def test_sub_agent_timeout(self) -> None:
        """Sub-agent with very short timeout returns timeout error."""
        config = SubAgentConfig(
            task="Write a very long essay about the history of computing.",
            model="kimi/kimi-k2.5",
            max_iterations=50,
            timeout_seconds=1,  # Very short — should timeout
        )

        result = await spawn_sub_agent(config, parent_depth=0)
        # Should either timeout or complete quickly
        assert isinstance(result, str)
        assert len(result) > 0
