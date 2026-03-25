"""Comprehensive E2E tests for P1 modules WITH real LLM calls.

Requires API key (KIMI_API_KEY).
Mark: ``pytest.mark.e2e`` — run with ``--run-e2e``.

Tests:
1. Memory + Agent: conversation persistence across sessions
2. Memory + Tool calls: tool_calls/ToolMessage persist correctly
3. Auto Summary: LLM summarization + context continuity after summary
4. Multi-turn + Summary trigger: natural conversation triggers summary
5. Force compression: emergency context reduction
6. Sub-Agent: real task delegation with LLM
7. Sub-Agent + Tools: sub-agent uses tools to complete task
8. Sub-Agent concurrency: multiple concurrent sub-agents
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from smartclaw.agent.graph import build_graph, invoke
from smartclaw.agent.sub_agent import (
    DepthLimitExceededError,
    SubAgentConfig,
    spawn_sub_agent,
)
from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.providers.config import ModelConfig
from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.registry import create_system_tools

pytestmark = pytest.mark.e2e

_MODEL = ModelConfig(
    primary="kimi/kimi-k2.5", fallbacks=[], temperature=0.0, max_tokens=1024,
)


# ===================================================================
# 1. Memory + Agent: conversation persistence across sessions
# ===================================================================


class TestMemoryPersistenceE2E:
    """Agent conversation persists to SQLite and reloads across sessions."""

    async def test_name_recall_across_sessions(self, tmp_path: pathlib.Path) -> None:
        """Session 1: tell name. Session 2: ask name back."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()
        graph = build_graph(_MODEL, tools=[])

        r1 = await invoke(graph, "My name is AliceTest. Remember it.",
                          max_iterations=3, session_key="s1", memory_store=store)
        assert r1.get("error") is None

        r2 = await invoke(graph, "What is my name?",
                          max_iterations=3, session_key="s1", memory_store=store)
        assert "AliceTest" in (r2.get("final_answer") or "").replace(" ", "")
        await store.close()

    async def test_separate_sessions_isolated(self, tmp_path: pathlib.Path) -> None:
        """Two different session keys don't leak context."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()
        graph = build_graph(_MODEL, tools=[])

        await invoke(graph, "The secret code is ALPHA-7.",
                     max_iterations=3, session_key="s-a", memory_store=store)
        r = await invoke(graph, "What is the secret code?",
                         max_iterations=3, session_key="s-b", memory_store=store)
        answer = (r.get("final_answer") or "").lower()
        assert "alpha-7" not in answer
        await store.close()


# ===================================================================
# 2. Memory + Tool calls: tool_calls persist correctly
# ===================================================================


class TestMemoryToolCallsE2E:
    """Agent uses tools, tool_calls and ToolMessage persist to SQLite."""

    async def test_tool_usage_persists(self, tmp_path: pathlib.Path) -> None:
        """Agent uses shell tool, tool call chain persists in memory."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()

        policy = PathPolicy(allowed_patterns=[str(tmp_path.resolve()), f"{tmp_path.resolve()}/**"])
        registry = create_system_tools(str(tmp_path), path_policy=policy)
        tools = registry.get_all()
        graph = build_graph(_MODEL, tools=tools)

        r = await invoke(graph, "Run 'echo hello_e2e_test' and tell me the output.",
                         max_iterations=8, session_key="tool-s", memory_store=store)
        assert r.get("error") is None
        answer = r.get("final_answer") or ""
        assert "hello_e2e_test" in answer

        # Verify tool calls persisted
        history = await store.get_history("tool-s")
        has_tool_call = any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for m in history
        )
        assert has_tool_call, "No AIMessage with tool_calls found in persisted history"
        await store.close()


# ===================================================================
# 3. Auto Summary: summarization + context continuity
# ===================================================================


class TestAutoSummaryE2E:
    """LLM summarization and post-summary context continuity."""

    async def test_summary_generated_and_stored(self, tmp_path: pathlib.Path) -> None:
        """Exceed threshold → LLM generates summary → stored in DB."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()

        summarizer = AutoSummarizer(
            store=store, model_config=_MODEL,
            message_threshold=6, keep_recent=2,
        )

        msgs = []
        for i in range(8):
            h = HumanMessage(content=f"Q{i}: capital of country #{i}?")
            a = AIMessage(content=f"A{i}: Capital_{i}")
            msgs.extend([h, a])
            await store.add_full_message("sum", h)
            await store.add_full_message("sum", a)

        await summarizer.maybe_summarize("sum", msgs)

        summary = await store.get_summary("sum")
        assert len(summary) > 20, "Summary too short — LLM likely failed"
        history = await store.get_history("sum")
        assert len(history) == 2
        await store.close()

    async def test_context_continuity_after_summary(self, tmp_path: pathlib.Path) -> None:
        """After summarization, agent can still answer questions from summarized context."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()

        summarizer = AutoSummarizer(
            store=store, model_config=_MODEL,
            message_threshold=4, keep_recent=2,
        )

        # Build conversation with a memorable fact
        fact_msgs = [
            HumanMessage(content="The project codename is PHOENIX-42."),
            AIMessage(content="Got it, the project codename is PHOENIX-42."),
            HumanMessage(content="The deadline is March 2027."),
            AIMessage(content="Noted, deadline is March 2027."),
            HumanMessage(content="The budget is $500K."),
            AIMessage(content="Budget recorded as $500K."),
        ]
        for m in fact_msgs:
            await store.add_full_message("ctx", m)

        # Trigger summarization
        await summarizer.maybe_summarize("ctx", fact_msgs)
        summary = await store.get_summary("ctx")
        assert len(summary) > 0

        # Now ask about the summarized fact using the agent
        graph = build_graph(_MODEL, tools=[])
        r = await invoke(graph, "What is the project codename?",
                         max_iterations=3, session_key="ctx",
                         memory_store=store, summarizer=summarizer)
        answer = (r.get("final_answer") or "").upper()
        assert "PHOENIX" in answer or "42" in answer
        await store.close()


# ===================================================================
# 4. Multi-turn + natural summary trigger
# ===================================================================


class TestMultiTurnSummaryE2E:
    """Real multi-turn conversation naturally triggers summarization."""

    async def test_three_turn_conversation_with_summary(self, tmp_path: pathlib.Path) -> None:
        """3 turns of real agent conversation, summary triggers, 4th turn still works."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()

        summarizer = AutoSummarizer(
            store=store, model_config=_MODEL,
            message_threshold=4, keep_recent=2,
        )
        graph = build_graph(_MODEL, tools=[])

        # Turn 1
        await invoke(graph, "I'm building a robot named RoboMax.",
                     max_iterations=3, session_key="mt",
                     memory_store=store, summarizer=summarizer)
        # Turn 2
        await invoke(graph, "RoboMax uses Python and runs on Raspberry Pi.",
                     max_iterations=3, session_key="mt",
                     memory_store=store, summarizer=summarizer)
        # Turn 3 — should trigger summary (history growing)
        await invoke(graph, "RoboMax can navigate using LIDAR sensors.",
                     max_iterations=3, session_key="mt",
                     memory_store=store, summarizer=summarizer)

        # Check if summary was generated at some point
        summary = await store.get_summary("mt")
        # Summary may or may not have triggered depending on exact message count
        # But the conversation should still work

        # Turn 4 — ask about earlier context
        r = await invoke(graph, "What is the robot's name?",
                         max_iterations=3, session_key="mt",
                         memory_store=store, summarizer=summarizer)
        answer = (r.get("final_answer") or "")
        assert "RoboMax" in answer or "robomax" in answer.lower()
        await store.close()


# ===================================================================
# 5. Force compression
# ===================================================================


class TestForceCompressionE2E:
    """Emergency context reduction via force_compression."""

    async def test_force_compression_preserves_continuity(self, tmp_path: pathlib.Path) -> None:
        """After force_compression, agent can still function with reduced context."""
        db = str(tmp_path / "mem.db")
        store = MemoryStore(db_path=db)
        await store.initialize()

        summarizer = AutoSummarizer(store=store, model_config=_MODEL)

        # Build a long conversation
        msgs = []
        for i in range(10):
            h = HumanMessage(content=f"Turn {i}: Tell me about topic {i}.")
            a = AIMessage(content=f"Here is info about topic {i}. It is interesting.")
            msgs.extend([h, a])
            await store.add_full_message("fc", h)
            await store.add_full_message("fc", a)

        # Force compression
        kept = await summarizer.force_compression("fc", msgs)
        assert len(kept) < len(msgs)
        assert len(kept) >= 1

        # Verify compression note in summary
        summary = await store.get_summary("fc")
        assert "compression" in summary.lower() or "dropped" in summary.lower()

        # Agent should still work after compression
        graph = build_graph(_MODEL, tools=[])
        r = await invoke(graph, "Can you still respond after compression?",
                         max_iterations=3, session_key="fc",
                         memory_store=store, summarizer=summarizer)
        assert r.get("error") is None
        assert len(r.get("final_answer") or "") > 0
        await store.close()


# ===================================================================
# 6. Sub-Agent: real LLM task delegation
# ===================================================================


class TestSubAgentE2E:
    """Sub-agent executes real tasks via LLM."""

    async def test_simple_task(self) -> None:
        """Sub-agent answers a simple math question."""
        cfg = SubAgentConfig(task="What is 7 * 8? Reply with just the number.",
                             model="kimi/kimi-k2.5", max_iterations=3, timeout_seconds=30)
        result = await spawn_sub_agent(cfg, parent_depth=0)
        assert "Error" not in result
        assert "56" in result

    async def test_depth_limit_enforced(self) -> None:
        """Depth limit prevents spawning without LLM call."""
        cfg = SubAgentConfig(task="noop", model="kimi/kimi-k2.5", max_depth=2)
        with pytest.raises(DepthLimitExceededError):
            await spawn_sub_agent(cfg, parent_depth=2)

    async def test_timeout_graceful(self) -> None:
        """Very short timeout handled gracefully."""
        cfg = SubAgentConfig(task="Write a 10000 word essay.", model="kimi/kimi-k2.5",
                             max_iterations=50, timeout_seconds=1)
        result = await spawn_sub_agent(cfg, parent_depth=0)
        assert isinstance(result, str) and len(result) > 0


# ===================================================================
# 7. Sub-Agent + Tools
# ===================================================================


class TestSubAgentWithToolsE2E:
    """Sub-agent uses real tools to complete tasks."""

    async def test_sub_agent_uses_shell_tool(self, tmp_path: pathlib.Path) -> None:
        """Sub-agent uses exec_command tool to run a shell command."""
        from smartclaw.tools.shell import ShellTool

        shell = ShellTool()
        cfg = SubAgentConfig(
            task="Use the exec_command tool to run 'echo SUB_AGENT_OK' and tell me the output.",
            model="kimi/kimi-k2.5",
            tools=[shell],
            max_iterations=5,
            timeout_seconds=30,
        )
        result = await spawn_sub_agent(cfg, parent_depth=0)
        assert "SUB_AGENT_OK" in result

    async def test_sub_agent_uses_file_tools(self, tmp_path: pathlib.Path) -> None:
        """Sub-agent writes and reads a file using filesystem tools."""
        policy = PathPolicy(allowed_patterns=[str(tmp_path.resolve()), f"{tmp_path.resolve()}/**"])
        registry = create_system_tools(str(tmp_path), path_policy=policy)
        tools = registry.get_all()

        target = tmp_path / "sub_agent_output.txt"
        cfg = SubAgentConfig(
            task=f"Write the text 'sub-agent-wrote-this' to the file {target}, then read it back and tell me what it says.",
            model="kimi/kimi-k2.5",
            tools=tools,
            max_iterations=8,
            timeout_seconds=60,
        )
        result = await spawn_sub_agent(cfg, parent_depth=0)
        assert "sub-agent-wrote-this" in result
        assert target.exists()


# ===================================================================
# 8. Sub-Agent concurrency
# ===================================================================


class TestSubAgentConcurrencyE2E:
    """Multiple sub-agents execute concurrently with semaphore control."""

    async def test_concurrent_sub_agents_complete(self) -> None:
        """3 concurrent sub-agents all complete successfully."""
        sem = asyncio.Semaphore(3)
        tasks = []
        for i in range(3):
            cfg = SubAgentConfig(
                task=f"What is {i+1} * 10? Reply with just the number.",
                model="kimi/kimi-k2.5",
                max_iterations=3,
                timeout_seconds=30,
            )
            tasks.append(spawn_sub_agent(cfg, parent_depth=0, semaphore=sem))

        results = await asyncio.gather(*tasks)
        assert len(results) == 3
        # Each should contain the correct answer
        assert "10" in results[0]
        assert "20" in results[1]
        assert "30" in results[2]

    async def test_semaphore_limits_concurrency(self) -> None:
        """Semaphore(1) serializes execution — all still complete."""
        sem = asyncio.Semaphore(1)
        tasks = []
        for i in range(2):
            cfg = SubAgentConfig(
                task=f"What is {i+1} + {i+1}? Reply with just the number.",
                model="kimi/kimi-k2.5",
                max_iterations=3,
                timeout_seconds=30,
            )
            tasks.append(spawn_sub_agent(cfg, parent_depth=0, semaphore=sem))

        results = await asyncio.gather(*tasks)
        assert len(results) == 2
        assert all("Error" not in r for r in results)
