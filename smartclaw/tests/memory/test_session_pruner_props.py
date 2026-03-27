"""Property-based tests for SessionPruner (Properties 14–16).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from smartclaw.memory.pruning import SessionPruner, SessionPrunerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _char_token_estimator(messages: list[BaseMessage]) -> int:
    """Simple char-based token estimator (2.5 chars ≈ 1 token)."""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(content) + 12  # per-message overhead
    return total * 2 // 5


def _make_tool_message(content: str, name: str = "some_tool") -> ToolMessage:
    """Create a ToolMessage with a tool_call_id and name."""
    return ToolMessage(content=content, tool_call_id="call_test", name=name)


# Strategy: generate a list of messages with a mix of types, ensuring
# ToolMessages are in the middle (prunable) range.
_tool_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)

_content = st.text(min_size=1, max_size=2000)


# ---------------------------------------------------------------------------
# Property 14: L2 两级裁剪阈值行为
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 14: L2 两级裁剪阈值行为
class TestTwoLevelPruningThresholds:
    """**Validates: Requirements 4.2, 4.3, 4.4**

    When tokens exceed soft_trim_threshold, ToolMessages in the prunable
    range are shortened (soft-trimmed to head+tail).  When exceeding
    hard_clear_threshold, ToolMessages in the prunable range are replaced
    with placeholder text ``[tool result cleared - {tool_name}]``.
    """

    @given(
        tool_content_len=st.integers(min_value=1500, max_value=5000),
        num_tool_msgs=st.integers(min_value=3, max_value=8),
        tool_name=_tool_names,
    )
    @settings(max_examples=100)
    def test_soft_trim_applied_above_soft_threshold(
        self,
        tool_content_len: int,
        num_tool_msgs: int,
        tool_name: str,
    ) -> None:
        """When tokens exceed soft_trim_threshold but not hard_clear_threshold,
        ToolMessages in the prunable range should be soft-trimmed."""
        soft_trim_head = 100
        soft_trim_tail = 80

        # Build messages: 2 head + N tool messages + 2 recent
        content = "X" * tool_content_len
        head_msgs: list[BaseMessage] = [
            HumanMessage(content="head1"),
            AIMessage(content="head2"),
        ]
        middle_msgs: list[BaseMessage] = [
            _make_tool_message(content, name=tool_name)
            for _ in range(num_tool_msgs)
        ]
        tail_msgs: list[BaseMessage] = [
            HumanMessage(content="recent1"),
            AIMessage(content="recent2"),
        ]
        messages = head_msgs + middle_msgs + tail_msgs

        # Calculate a context_window that puts us above soft but below hard
        token_count = _char_token_estimator(messages)
        # soft_threshold = 0.3 so context_window * 0.3 < token_count
        # hard_threshold = 0.9 so context_window * 0.9 > token_count
        context_window = int(token_count / 0.35)

        config = SessionPrunerConfig(
            soft_trim_threshold=0.3,
            hard_clear_threshold=0.9,
            soft_trim_head=soft_trim_head,
            soft_trim_tail=soft_trim_tail,
            keep_recent=2,
            keep_head=2,
        )
        pruner = SessionPruner(config, context_window, _char_token_estimator)
        result = pruner.prune(messages)

        assert len(result) == len(messages)

        # Middle ToolMessages should be soft-trimmed (shorter than original)
        for i in range(2, 2 + num_tool_msgs):
            msg = result[i]
            assert isinstance(msg, ToolMessage)
            result_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > soft_trim_head + soft_trim_tail:
                # Should be trimmed
                assert len(result_content) < len(content)
                # Should start with head chars
                assert result_content[:soft_trim_head] == content[:soft_trim_head]
                # Should contain "..."
                assert "..." in result_content
            # Should NOT be hard-cleared
            assert not result_content.startswith("[tool result cleared")

    @given(
        tool_content_len=st.integers(min_value=1500, max_value=5000),
        num_tool_msgs=st.integers(min_value=3, max_value=8),
        tool_name=_tool_names,
    )
    @settings(max_examples=100)
    def test_hard_clear_applied_above_hard_threshold(
        self,
        tool_content_len: int,
        num_tool_msgs: int,
        tool_name: str,
    ) -> None:
        """When tokens exceed hard_clear_threshold, ToolMessages in the
        prunable range should be replaced with placeholder."""
        content = "Y" * tool_content_len
        head_msgs: list[BaseMessage] = [
            HumanMessage(content="head1"),
            AIMessage(content="head2"),
        ]
        middle_msgs: list[BaseMessage] = [
            _make_tool_message(content, name=tool_name)
            for _ in range(num_tool_msgs)
        ]
        tail_msgs: list[BaseMessage] = [
            HumanMessage(content="recent1"),
            AIMessage(content="recent2"),
        ]
        messages = head_msgs + middle_msgs + tail_msgs

        token_count = _char_token_estimator(messages)
        # Set context_window so token_count > hard_threshold
        context_window = int(token_count / 0.8)

        config = SessionPrunerConfig(
            soft_trim_threshold=0.3,
            hard_clear_threshold=0.7,
            keep_recent=2,
            keep_head=2,
        )
        pruner = SessionPruner(config, context_window, _char_token_estimator)
        result = pruner.prune(messages)

        assert len(result) == len(messages)

        # Middle ToolMessages should be hard-cleared
        for i in range(2, 2 + num_tool_msgs):
            msg = result[i]
            assert isinstance(msg, ToolMessage)
            result_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            assert result_content == f"[tool result cleared - {tool_name}]"


# ---------------------------------------------------------------------------
# Property 15: L2 裁剪保留头尾消息
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 15: L2 裁剪保留头尾消息
class TestPruningPreservesHeadAndTail:
    """**Validates: Requirements 4.6**

    The first keep_head messages and the last keep_recent messages should
    remain unchanged (content identical to the original) after any pruning.
    """

    @given(
        keep_head=st.integers(min_value=1, max_value=4),
        keep_recent=st.integers(min_value=1, max_value=4),
        num_middle=st.integers(min_value=2, max_value=8),
        tool_content_len=st.integers(min_value=1500, max_value=5000),
    )
    @settings(max_examples=100)
    def test_head_and_tail_messages_unchanged(
        self,
        keep_head: int,
        keep_recent: int,
        num_middle: int,
        tool_content_len: int,
    ) -> None:
        content = "Z" * tool_content_len

        # Build head messages (mix of Human/AI)
        head_msgs: list[BaseMessage] = []
        for i in range(keep_head):
            if i % 2 == 0:
                head_msgs.append(HumanMessage(content=f"head_{i}"))
            else:
                head_msgs.append(AIMessage(content=f"head_{i}"))

        # Build middle ToolMessages
        middle_msgs: list[BaseMessage] = [
            _make_tool_message(content, name=f"tool_{i}")
            for i in range(num_middle)
        ]

        # Build tail messages
        tail_msgs: list[BaseMessage] = []
        for i in range(keep_recent):
            if i % 2 == 0:
                tail_msgs.append(HumanMessage(content=f"tail_{i}"))
            else:
                tail_msgs.append(AIMessage(content=f"tail_{i}"))

        messages = head_msgs + middle_msgs + tail_msgs

        # Force pruning by setting a small context_window
        token_count = _char_token_estimator(messages)
        context_window = int(token_count / 0.8)

        config = SessionPrunerConfig(
            soft_trim_threshold=0.3,
            hard_clear_threshold=0.7,
            keep_recent=keep_recent,
            keep_head=keep_head,
        )
        pruner = SessionPruner(config, context_window, _char_token_estimator)
        result = pruner.prune(messages)

        assert len(result) == len(messages)

        # Head messages unchanged
        for i in range(keep_head):
            orig_content = messages[i].content
            result_content = result[i].content
            assert result_content == orig_content, (
                f"Head message {i} was modified: {result_content!r} != {orig_content!r}"
            )

        # Tail messages unchanged
        for i in range(keep_recent):
            idx = len(messages) - keep_recent + i
            orig_content = messages[idx].content
            result_content = result[idx].content
            assert result_content == orig_content, (
                f"Tail message {idx} was modified: {result_content!r} != {orig_content!r}"
            )


# ---------------------------------------------------------------------------
# Property 16: L2 allow_list 消息不被裁剪
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 16: L2 allow_list 消息不被裁剪
class TestAllowListMessagesNeverModified:
    """**Validates: Requirements 4.5**

    ToolMessages from tools in tool_allow_list are never modified by the
    SessionPruner, regardless of token thresholds.
    """

    @given(
        allowed_tool=_tool_names,
        other_tool=_tool_names,
        tool_content_len=st.integers(min_value=1500, max_value=5000),
        num_allowed=st.integers(min_value=1, max_value=3),
        num_other=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    def test_allow_list_tools_never_pruned(
        self,
        allowed_tool: str,
        other_tool: str,
        tool_content_len: int,
        num_allowed: int,
        num_other: int,
    ) -> None:
        # Ensure distinct tool names
        if other_tool == allowed_tool:
            other_tool = allowed_tool + "_other"

        content = "W" * tool_content_len

        head_msgs: list[BaseMessage] = [
            HumanMessage(content="head1"),
            AIMessage(content="head2"),
        ]

        # Interleave allowed and non-allowed ToolMessages in the middle
        middle_msgs: list[BaseMessage] = []
        for i in range(num_allowed + num_other):
            if i < num_allowed:
                middle_msgs.append(_make_tool_message(content, name=allowed_tool))
            else:
                middle_msgs.append(_make_tool_message(content, name=other_tool))

        tail_msgs: list[BaseMessage] = [
            HumanMessage(content="recent1"),
            AIMessage(content="recent2"),
        ]
        messages = head_msgs + middle_msgs + tail_msgs

        # Force hard-clear level pruning
        token_count = _char_token_estimator(messages)
        context_window = int(token_count / 0.8)

        config = SessionPrunerConfig(
            soft_trim_threshold=0.3,
            hard_clear_threshold=0.7,
            keep_recent=2,
            keep_head=2,
            tool_allow_list=[allowed_tool],
        )
        pruner = SessionPruner(config, context_window, _char_token_estimator)
        result = pruner.prune(messages)

        assert len(result) == len(messages)

        # Allowed tool messages in the middle should be unchanged
        for i in range(2, 2 + num_allowed):
            msg = result[i]
            assert isinstance(msg, ToolMessage)
            result_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            assert result_content == content, (
                f"Allow-listed ToolMessage at index {i} was modified"
            )

        # Non-allowed tool messages in the middle should be pruned
        for i in range(2 + num_allowed, 2 + num_allowed + num_other):
            msg = result[i]
            assert isinstance(msg, ToolMessage)
            result_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Should be hard-cleared (since we're above hard threshold)
            assert result_content == f"[tool result cleared - {other_tool}]"
