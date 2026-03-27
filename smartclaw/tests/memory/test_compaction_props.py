"""Property-based tests for L3 pre-compaction memory flush and L4 multi-stage compaction (Properties 17–23).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer, _HARDCODED_FALLBACK
from smartclaw.providers.config import ModelConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_SUMMARY = "Mock summary of the conversation segment."


def _make_model_config() -> ModelConfig:
    return ModelConfig(primary="openai/gpt-4o-mini")


def _human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def _ai(content: str) -> AIMessage:
    return AIMessage(content=content)


def _tool(content: str, name: str = "some_tool") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call_test", name=name)


# Strategies
_content = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
_short_content = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Property 17: L3 摘要追加合并
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 17: L3 摘要追加合并
class TestL3SummaryMergeFormat:
    """**Validates: Requirements 5.3**

    For any existing summary string and new L3 flush summary, after
    _memory_flush, the summary stored in MemoryStore should equal
    ``existing_summary + "\\n\\n---\\n\\n" + new_flush_summary``.
    """

    @given(
        existing_summary=_content,
        flush_result=_content,
        num_messages=st.integers(min_value=2, max_value=6),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_l3_summary_merge_format(
        self,
        tmp_path: Path,
        existing_summary: str,
        flush_result: str,
        num_messages: int,
    ) -> None:
        import uuid

        db_path = str(tmp_path / f"test_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            await store.set_summary("s1", existing_summary)

            summarizer = AutoSummarizer(
                store, _make_model_config(),
                compaction_model="openai/gpt-4o-mini",
            )

            messages: list[BaseMessage] = []
            for i in range(num_messages):
                messages.append(_human(f"user msg {i}"))
                messages.append(_ai(f"ai msg {i}"))

            with patch.object(
                summarizer, "_call_llm_summarize_with_config",
                new_callable=AsyncMock,
                return_value=flush_result,
            ):
                await summarizer._memory_flush("s1", messages)

            stored = await store.get_summary("s1")
            expected = existing_summary + "\n\n---\n\n" + flush_result
            assert stored == expected
        finally:
            await store.close()

    @given(
        flush_result=_content,
        num_messages=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_l3_summary_no_existing(
        self,
        tmp_path: Path,
        flush_result: str,
        num_messages: int,
    ) -> None:
        """When no existing summary, flush result is stored directly."""
        import uuid

        db_path = str(tmp_path / f"test_no_existing_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            summarizer = AutoSummarizer(store, _make_model_config())

            messages: list[BaseMessage] = [
                _human(f"msg {i}") for i in range(num_messages)
            ]

            with patch.object(
                summarizer, "_call_llm_summarize_with_config",
                new_callable=AsyncMock,
                return_value=flush_result,
            ):
                await summarizer._memory_flush("s1", messages)

            stored = await store.get_summary("s1")
            assert stored == flush_result
        finally:
            await store.close()



# ---------------------------------------------------------------------------
# Property 18: L3 失败不中断 L4
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 18: L3 失败不中断 L4
class TestL3FailureDoesNotBlockL4:
    """**Validates: Requirements 5.1, 5.4**

    For any L3 memory flush that fails (LLM call raises exception),
    the L4 multi-stage compaction should still execute and produce a
    valid summary.
    """

    @given(
        num_turns=st.integers(min_value=3, max_value=8),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_l3_failure_l4_still_runs(
        self,
        tmp_path: Path,
        num_turns: int,
    ) -> None:
        import uuid

        db_path = str(tmp_path / f"test_l3fail_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            messages: list[BaseMessage] = []
            for i in range(num_turns):
                messages.append(_human(f"user msg {i}"))
                messages.append(_ai(f"ai msg {i}"))

            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(
                store, _make_model_config(),
                message_threshold=1,
                token_percent_threshold=1,
                context_window=100,
                keep_recent=2,
            )

            # L3 _memory_flush will fail, but L4 _summarize_with_fallback should succeed
            l3_call_count = 0
            l4_call_count = 0

            original_flush = summarizer._memory_flush
            original_fallback = summarizer._summarize_with_fallback

            async def failing_flush(session_key, msgs):
                nonlocal l3_call_count
                l3_call_count += 1
                raise RuntimeError("L3 LLM call failed")

            async def mock_fallback(session_key, msgs, existing_summary):
                nonlocal l4_call_count
                l4_call_count += 1
                return _MOCK_SUMMARY

            with patch.object(summarizer, "_memory_flush", side_effect=failing_flush):
                with patch.object(summarizer, "_summarize_with_fallback", side_effect=mock_fallback):
                    result = await summarizer.maybe_summarize("s1", messages)

            # L3 was attempted (and failed)
            assert l3_call_count == 1
            # L4 still executed
            assert l4_call_count == 1
            # Summary was stored
            stored = await store.get_summary("s1")
            assert stored == _MOCK_SUMMARY
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Property 19: L4 分块在 turn boundary 切分
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 19: L4 分块在 turn boundary 切分
class TestL4ChunksSplitAtTurnBoundary:
    """**Validates: Requirements 6.1**

    For any message list chunked by _chunk_messages, each chunk boundary
    should occur at a HumanMessage position, and no AIMessage with
    tool_calls should be separated from its corresponding ToolMessages.
    """

    @given(
        num_turns=st.integers(min_value=2, max_value=10),
        content_len=st.integers(min_value=50, max_value=500),
        chunk_max_tokens=st.integers(min_value=20, max_value=200),
    )
    @settings(max_examples=100, deadline=None)
    def test_chunks_start_at_human_message(
        self,
        num_turns: int,
        content_len: int,
        chunk_max_tokens: int,
    ) -> None:
        messages: list[BaseMessage] = []
        for i in range(num_turns):
            messages.append(_human("x" * content_len))
            messages.append(_ai("y" * content_len))

        store_mock = MagicMock()
        summarizer = AutoSummarizer(
            store_mock, _make_model_config(),
            chunk_max_tokens=chunk_max_tokens,
        )

        chunks = summarizer._chunk_messages(messages, chunk_max_tokens)

        # All chunks should be non-empty
        for chunk in chunks:
            assert len(chunk) > 0

        # All messages should be present (no loss)
        all_msgs = [msg for chunk in chunks for msg in chunk]
        assert len(all_msgs) == len(messages)

        # Every chunk after the first should start with a HumanMessage
        # (the first chunk starts wherever the messages start)
        for i, chunk in enumerate(chunks):
            if i > 0:
                assert isinstance(chunk[0], HumanMessage), (
                    f"Chunk {i} starts with {type(chunk[0]).__name__}, "
                    f"expected HumanMessage"
                )


# ---------------------------------------------------------------------------
# Property 20: L4 渐进回退策略
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 20: L4 渐进回退策略
class TestL4ProgressiveFallback:
    """**Validates: Requirements 6.4**

    For any compression attempt, if the initial full compression fails,
    the system should attempt filtering oversized ToolMessages, then
    use hardcoded fallback text. The final result should always be non-None.
    """

    @given(
        num_messages=st.integers(min_value=2, max_value=6),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_progressive_fallback_full_then_filter_then_hardcoded(
        self,
        tmp_path: Path,
        num_messages: int,
    ) -> None:
        import uuid

        db_path = str(tmp_path / f"test_fallback_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            messages: list[BaseMessage] = []
            for i in range(num_messages):
                messages.append(_human(f"msg {i}"))
                messages.append(_ai(f"reply {i}"))

            summarizer = AutoSummarizer(store, _make_model_config())

            # All LLM calls fail → should fall through to hardcoded fallback
            with patch.object(
                summarizer, "_multi_stage_compact",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_compact:
                result = await summarizer._summarize_with_fallback(
                    "s1", messages, ""
                )

            # Should have been called twice (full + filtered)
            assert mock_compact.call_count == 2
            # Final result is the hardcoded fallback
            assert result == _HARDCODED_FALLBACK
        finally:
            await store.close()

    @given(
        num_messages=st.integers(min_value=2, max_value=6),
        summary_text=_content,
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_progressive_fallback_succeeds_on_first_attempt(
        self,
        tmp_path: Path,
        num_messages: int,
        summary_text: str,
    ) -> None:
        import uuid

        db_path = str(tmp_path / f"test_fallback_ok_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            messages: list[BaseMessage] = [
                _human(f"msg {i}") for i in range(num_messages)
            ]

            summarizer = AutoSummarizer(store, _make_model_config())

            with patch.object(
                summarizer, "_multi_stage_compact",
                new_callable=AsyncMock,
                return_value=summary_text,
            ) as mock_compact:
                result = await summarizer._summarize_with_fallback(
                    "s1", messages, ""
                )

            # Only called once (first attempt succeeded)
            assert mock_compact.call_count == 1
            assert result == summary_text
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Property 21: L4 identifier_policy 指令生成
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 21: L4 identifier_policy 指令生成
class TestIdentifierPolicyInstructions:
    """**Validates: Requirements 6.5**

    For any identifier_policy value, _build_identifier_instructions should
    return: non-empty preservation instructions for "strict", user-specified
    patterns for "custom", and empty string for "off".
    """

    @given(
        patterns=st.lists(
            st.text(min_size=1, max_size=30).filter(lambda s: s.strip()),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_strict_returns_nonempty(self, patterns: list[str]) -> None:
        store_mock = MagicMock()
        summarizer = AutoSummarizer(
            store_mock, _make_model_config(),
            identifier_policy="strict",
        )
        result = summarizer._build_identifier_instructions()
        assert len(result) > 0
        assert "preserve" in result.lower() or "MUST" in result

    @given(
        patterns=st.lists(
            st.text(min_size=1, max_size=30).filter(lambda s: s.strip()),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_custom_includes_patterns(self, patterns: list[str]) -> None:
        store_mock = MagicMock()
        summarizer = AutoSummarizer(
            store_mock, _make_model_config(),
            identifier_policy="custom",
            identifier_patterns=patterns,
        )
        result = summarizer._build_identifier_instructions()
        assert len(result) > 0
        # All patterns should appear in the instructions
        for pattern in patterns:
            assert pattern in result

    @settings(max_examples=100)
    @given(data=st.data())
    def test_off_returns_empty(self, data: st.DataObject) -> None:
        store_mock = MagicMock()
        summarizer = AutoSummarizer(
            store_mock, _make_model_config(),
            identifier_policy="off",
        )
        result = summarizer._build_identifier_instructions()
        assert result == ""

    @settings(max_examples=100)
    @given(data=st.data())
    def test_custom_no_patterns_returns_empty(self, data: st.DataObject) -> None:
        """Custom policy with no patterns should return empty string."""
        store_mock = MagicMock()
        summarizer = AutoSummarizer(
            store_mock, _make_model_config(),
            identifier_policy="custom",
            identifier_patterns=[],
        )
        result = summarizer._build_identifier_instructions()
        assert result == ""


# ---------------------------------------------------------------------------
# Property 22: L4 溢出自动恢复重试
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 22: L4 溢出自动恢复重试
class TestOverflowRecoveryRetries:
    """**Validates: Requirements 6.7**

    For any post-compression state that still exceeds the context window,
    the overflow recovery should retry up to 3 times, with each retry
    using chunk_max_tokens halved from the previous attempt.
    """

    @given(
        initial_chunk_max=st.integers(min_value=200, max_value=8000),
        num_messages=st.integers(min_value=4, max_value=8),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_overflow_recovery_halves_chunk_max(
        self,
        tmp_path: Path,
        initial_chunk_max: int,
        num_messages: int,
    ) -> None:
        import uuid

        db_path = str(tmp_path / f"test_overflow_{uuid.uuid4().hex}.db")
        store = MemoryStore(db_path=db_path)
        await store.initialize()
        try:
            messages: list[BaseMessage] = []
            for i in range(num_messages):
                messages.append(_human(f"user {i}"))
                messages.append(_ai(f"ai {i}"))

            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(
                store, _make_model_config(),
                chunk_max_tokens=initial_chunk_max,
                keep_recent=2,
            )

            # Track chunk_max_tokens values passed to _multi_stage_compact
            observed_chunk_maxes: list[int] = []

            async def tracking_compact(session_key, msgs, existing_summary, chunk_max_tokens=None):
                observed_chunk_maxes.append(chunk_max_tokens)
                # Succeed on the 3rd attempt
                if len(observed_chunk_maxes) >= 3:
                    return "recovered summary"
                return None

            with patch.object(summarizer, "_multi_stage_compact", side_effect=tracking_compact):
                with patch("smartclaw.memory.summarizer.asyncio.sleep", new_callable=AsyncMock):
                    result = await summarizer._overflow_recovery("s1", messages)

            # Should have retried with halved chunk_max_tokens
            assert len(observed_chunk_maxes) == 3
            expected = initial_chunk_max
            for i, observed in enumerate(observed_chunk_maxes):
                expected = max(expected // 2, 100)
                assert observed == expected, (
                    f"Attempt {i+1}: expected chunk_max_tokens={expected}, got {observed}"
                )
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Property 23: 上下文溢出错误检测触发 force_compression
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 23: 上下文溢出错误检测触发 force_compression
class TestContextOverflowDetection:
    """**Validates: Requirements 6.8**

    For any HTTP 400 error whose message contains keywords "context",
    "token", or "length", reasoning_node should trigger force_compression
    and retry the LLM call.
    """

    @given(
        keyword=st.sampled_from(["context", "token", "length"]),
        prefix=st.text(min_size=0, max_size=20),
    )
    @settings(max_examples=100, deadline=None)
    async def test_overflow_error_triggers_force_compression(
        self,
        keyword: str,
        prefix: str,
    ) -> None:
        from smartclaw.agent.nodes import _is_context_overflow_error, reasoning_node

        # Build an exception that looks like HTTP 400 with overflow keyword
        error_msg = f"{prefix} {keyword} limit exceeded"
        exc = Exception(error_msg)
        exc.status_code = 400  # type: ignore[attr-defined]

        assert _is_context_overflow_error(exc) is True

        # Now test the full reasoning_node flow
        call_count = 0

        async def mock_llm_call(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc
            return AIMessage(content="retry succeeded")

        mock_summarizer = AsyncMock()
        mock_summarizer.force_compression = AsyncMock(
            return_value=[HumanMessage(content="compressed")]
        )

        state = {
            "messages": [HumanMessage(content="hello")],
            "iteration": 0,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
            "session_key": "test_session",
            "summary": None,
            "sub_agent_depth": None,
        }

        result = await reasoning_node(
            state,
            llm_call=mock_llm_call,
            summarizer=mock_summarizer,
            session_key="test_session",
        )

        # force_compression should have been called
        mock_summarizer.force_compression.assert_called_once()
        # LLM was called twice (original + retry)
        assert call_count == 2
        # Result should be the retry response
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "retry succeeded"

    @given(
        non_overflow_msg=st.text(min_size=1, max_size=50).filter(
            lambda s: not any(kw in s.lower() for kw in ("context", "token", "length"))
        ),
    )
    @settings(max_examples=100, deadline=None)
    async def test_non_overflow_error_does_not_trigger_compression(
        self,
        non_overflow_msg: str,
    ) -> None:
        from smartclaw.agent.nodes import _is_context_overflow_error

        exc = Exception(non_overflow_msg)
        exc.status_code = 400  # type: ignore[attr-defined]

        # Should NOT be detected as context overflow
        assert _is_context_overflow_error(exc) is False

    @given(
        keyword=st.sampled_from(["context", "token", "length"]),
    )
    @settings(max_examples=100, deadline=None)
    async def test_non_400_error_with_keyword_not_detected(
        self,
        keyword: str,
    ) -> None:
        from smartclaw.agent.nodes import _is_context_overflow_error

        # Error with keyword but NOT HTTP 400
        exc = Exception(f"{keyword} issue occurred")
        exc.status_code = 500  # type: ignore[attr-defined]

        assert _is_context_overflow_error(exc) is False
