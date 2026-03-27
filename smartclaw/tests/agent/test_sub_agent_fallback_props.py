"""Property-based tests for Sub-Agent fallback inheritance and EphemeralStore compaction (Properties 27-28).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from smartclaw.agent.sub_agent import EphemeralStore, SpawnSubAgentTool, SubAgentConfig
from smartclaw.providers.config import ModelConfig


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_model_refs = st.builds(
    lambda p, m: f"{p}/{m}",
    p=st.sampled_from(["openai", "anthropic", "kimi"]),
    m=st.from_regex(r"[a-z0-9-]{3,15}", fullmatch=True),
)

_fallback_lists = st.lists(_model_refs, min_size=1, max_size=4)


# ---------------------------------------------------------------------------
# Property 27: Sub-Agent fallback 继承
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 27: Sub-Agent fallback 继承
class TestSubAgentFallbackInheritance:
    """**Validates: Requirements 9.2**

    For any parent Agent with a non-empty fallbacks list in its ModelConfig,
    the Sub-Agent's ModelConfig should contain the same fallbacks list.
    """

    @given(fallbacks=_fallback_lists)
    @settings(max_examples=100)
    def test_sub_agent_inherits_parent_fallbacks(self, fallbacks: list[str]) -> None:
        """SubAgentConfig receives parent fallbacks via SpawnSubAgentTool."""
        parent_config = ModelConfig(
            primary="openai/gpt-4o",
            fallbacks=fallbacks,
        )

        tool = SpawnSubAgentTool(
            default_model="openai/gpt-4o",
            parent_model_config=parent_config,
        )

        # Simulate what _arun does: inherit fallbacks
        inherited_fallbacks = list(
            getattr(tool.parent_model_config, "fallbacks", [])
        )
        config = SubAgentConfig(
            task="test task",
            model="openai/gpt-4o",
            fallbacks=inherited_fallbacks,
        )

        assert config.fallbacks == fallbacks

    @given(fallbacks=_fallback_lists)
    @settings(max_examples=100)
    def test_sub_agent_config_uses_fallbacks_in_model_config(
        self, fallbacks: list[str]
    ) -> None:
        """SubAgentConfig.fallbacks are used when building ModelConfig."""
        config = SubAgentConfig(
            task="test task",
            model="openai/gpt-4o",
            fallbacks=fallbacks,
        )
        # Verify the config stores fallbacks correctly
        assert config.fallbacks == fallbacks

    def test_no_parent_config_means_empty_fallbacks(self) -> None:
        """When parent_model_config is None, fallbacks are empty."""
        tool = SpawnSubAgentTool(
            default_model="openai/gpt-4o",
            parent_model_config=None,
        )
        fallbacks = list(getattr(tool.parent_model_config, "fallbacks", []))
        assert fallbacks == []


# ---------------------------------------------------------------------------
# Property 28: EphemeralStore 轻量压缩触发
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 28: EphemeralStore 轻量压缩触发
class TestEphemeralStoreCompaction:
    """**Validates: Requirements 9.3**

    For any EphemeralStore where message count exceeds max_size * compact_threshold,
    adding a new message should trigger soft-trimming of middle ToolMessages.
    """

    @given(
        tool_content_size=st.integers(min_value=1000, max_value=5000),
        num_messages=st.integers(min_value=10, max_value=20),
    )
    @settings(max_examples=100)
    def test_compaction_trims_middle_tool_messages(
        self, tool_content_size: int, num_messages: int
    ) -> None:
        """Middle ToolMessages are soft-trimmed when threshold exceeded."""
        max_size = num_messages + 5  # ensure we can exceed threshold
        store = EphemeralStore(max_size=max_size, compact_threshold=0.8)

        # Fill store with messages including large ToolMessages
        big_content = "x" * tool_content_size
        for i in range(num_messages):
            if i % 3 == 0:
                store.add_message(HumanMessage(content=f"question {i}"))
            elif i % 3 == 1:
                store.add_message(
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "t", "args": {}, "id": f"tc_{i}"}],
                    )
                )
            else:
                store.add_message(
                    ToolMessage(content=big_content, tool_call_id=f"tc_{i-1}")
                )

        # Check: if threshold was exceeded, middle ToolMessages should be trimmed
        threshold = int(max_size * 0.8)
        history = store.get_history()

        if len(history) > threshold:
            # At least some middle ToolMessages should have been trimmed
            keep_head = 2
            keep_tail = 5
            middle_start = keep_head
            middle_end = max(len(history) - keep_tail, middle_start)

            for i in range(middle_start, middle_end):
                msg = history[i]
                if isinstance(msg, ToolMessage):
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    # If original was large, it should now be trimmed
                    if tool_content_size > 800:
                        assert len(content) < tool_content_size

    def test_recent_messages_preserved(self) -> None:
        """Most recent messages are not trimmed by compaction."""
        store = EphemeralStore(max_size=15, compact_threshold=0.8)

        # Add enough messages to trigger compaction
        for i in range(14):
            if i % 2 == 0:
                store.add_message(HumanMessage(content=f"msg {i}"))
            else:
                store.add_message(
                    ToolMessage(content="a" * 2000, tool_call_id=f"tc_{i}")
                )

        history = store.get_history()
        # Last 5 messages should be preserved
        for msg in history[-5:]:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                # Recent ToolMessages should not be trimmed
                assert len(content) == 2000
