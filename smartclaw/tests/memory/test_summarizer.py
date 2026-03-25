"""Unit tests for AutoSummarizer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.providers.config import ModelConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_config() -> ModelConfig:
    return ModelConfig(primary="openai/gpt-4o-mini")


def _human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def _ai(content: str) -> AIMessage:
    return AIMessage(content=content)


def _make_conversation(num_turns: int) -> list[BaseMessage]:
    """Create a conversation with num_turns (human, ai) pairs."""
    msgs: list[BaseMessage] = []
    for i in range(num_turns):
        msgs.append(_human(f"User message {i}"))
        msgs.append(_ai(f"AI response {i}"))
    return msgs


# ---------------------------------------------------------------------------
# LLM call failure skips summarization (Req 2.9)
# ---------------------------------------------------------------------------


class TestLLMFailureSkipsSummarization:
    """LLM call failure skips summarization, returns original messages."""

    async def test_llm_failure_returns_original(self, tmp_path: Path) -> None:
        """When _call_llm_summarize returns None, messages are unchanged. (Req 2.9)"""
        messages = _make_conversation(15)

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(
                store,
                _make_model_config(),
                message_threshold=5,  # Will trigger
                keep_recent=3,
            )

            with patch.object(
                summarizer, "_call_llm_summarize", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = None  # Simulate failure
                result = await summarizer.maybe_summarize("s1", messages)

            # Should return original messages unchanged
            assert result == messages
            # Summary should NOT have been set
            summary = await store.get_summary("s1")
            assert summary == ""
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# < 4 messages: force_compression skips (Req 2.12)
# ---------------------------------------------------------------------------


class TestForceCompressionSkipsSmall:
    """force_compression skips when < 4 messages."""

    async def test_fewer_than_4_messages_skips(self, tmp_path: Path) -> None:
        """force_compression returns messages unchanged when < 4. (Req 2.12)"""
        messages = [_human("hello"), _ai("hi"), _human("bye")]
        assert len(messages) < 4

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            summarizer = AutoSummarizer(store, _make_model_config())
            result = await summarizer.force_compression("s1", messages)
            assert result == messages
        finally:
            await store.close()

    async def test_exactly_3_messages_skips(self, tmp_path: Path) -> None:
        """force_compression with exactly 3 messages returns unchanged. (Req 2.12)"""
        messages = [_human("a"), _ai("b"), _human("c")]

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            summarizer = AutoSummarizer(store, _make_model_config())
            result = await summarizer.force_compression("s1", messages)
            assert result == messages
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# No safe turn boundary: keep only most recent user message (Req 2.13)
# ---------------------------------------------------------------------------


class TestForceCompressionNoSafeBoundary:
    """force_compression falls back to keeping most recent user message."""

    async def test_no_safe_boundary_keeps_recent_user(self, tmp_path: Path) -> None:
        """When no safe turn boundary exists, keep only most recent user message. (Req 2.13)"""
        # All AI messages except the last one is a HumanMessage — but the midpoint
        # boundary search returns 0 (no HumanMessage at or before mid).
        # Construct: [AI, AI, AI, AI, Human] — mid=2, no HumanMessage at index <=2
        messages: list[BaseMessage] = [
            _ai("ai 0"),
            _ai("ai 1"),
            _ai("ai 2"),
            _ai("ai 3"),
            _human("last user msg"),
        ]

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(store, _make_model_config())
            result = await summarizer.force_compression("s1", messages)

            # Should keep only the most recent HumanMessage
            assert len(result) == 1
            assert isinstance(result[0], HumanMessage)
            assert result[0].content == "last user msg"
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Incremental summary includes old summary (Req 2.7)
# ---------------------------------------------------------------------------


class TestIncrementalSummary:
    """Incremental summary includes old summary in LLM prompt."""

    async def test_incremental_summary_includes_old(self, tmp_path: Path) -> None:
        """When existing summary exists, LLM prompt includes it. (Req 2.7)"""
        old_summary = "Previous context: user asked about Python."
        messages = _make_conversation(15)

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            # Set existing summary
            await store.set_summary("s1", old_summary)
            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(
                store,
                _make_model_config(),
                message_threshold=5,
                keep_recent=3,
            )

            captured_prompt: str | None = None

            async def capture_prompt(prompt: str) -> str | None:
                nonlocal captured_prompt
                captured_prompt = prompt
                return "New incremental summary."

            with patch.object(
                summarizer, "_call_llm_summarize", side_effect=capture_prompt
            ):
                await summarizer.maybe_summarize("s1", messages)

            # The prompt sent to LLM should contain the old summary
            assert captured_prompt is not None
            assert old_summary in captured_prompt
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Token percentage threshold triggers (Req 2.2)
# ---------------------------------------------------------------------------


class TestTokenPercentageThreshold:
    """Token percentage threshold triggers summarization."""

    async def test_token_threshold_triggers(self, tmp_path: Path) -> None:
        """Summarization triggers when token estimate exceeds percentage threshold. (Req 2.2)"""
        # Create enough turns with long content to exceed token threshold
        # but keep message count below message_threshold.
        # Need multiple turns so find_safe_boundary can locate a HumanMessage.
        long_content = "x" * 500
        messages = _make_conversation(6)  # 12 messages with proper turn structure
        # Replace content with long strings to push token estimate up
        messages = [
            _human(long_content) if isinstance(m, HumanMessage) else _ai(long_content)
            for m in messages
        ]

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            for msg in messages:
                await store.add_full_message("s1", msg)

            summarizer = AutoSummarizer(
                store,
                _make_model_config(),
                message_threshold=100,  # Won't trigger by count
                token_percent_threshold=10,  # Low threshold — will trigger by tokens
                context_window=1000,  # Small window
                keep_recent=2,
            )

            token_estimate = summarizer.estimate_tokens(messages)
            token_limit = 1000 * 10 // 100  # = 100 tokens
            # Verify our setup: tokens should exceed the limit
            assert token_estimate > token_limit, (
                f"Token estimate {token_estimate} should exceed limit {token_limit}"
            )

            with patch.object(
                summarizer, "_call_llm_summarize", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "Token-triggered summary."
                await summarizer.maybe_summarize("s1", messages)

            # LLM should have been called (triggered by token threshold)
            mock_llm.assert_called_once()
        finally:
            await store.close()

    async def test_below_both_thresholds_no_trigger(self, tmp_path: Path) -> None:
        """No summarization when both thresholds are not exceeded. (Req 2.2)"""
        messages = [_human("hi"), _ai("hello")]

        store = MemoryStore(db_path=str(tmp_path / "test.db"))
        await store.initialize()
        try:
            summarizer = AutoSummarizer(
                store,
                _make_model_config(),
                message_threshold=100,
                token_percent_threshold=90,
                context_window=200_000,
                keep_recent=1,
            )

            with patch.object(
                summarizer, "_call_llm_summarize", new_callable=AsyncMock
            ) as mock_llm:
                result = await summarizer.maybe_summarize("s1", messages)

            # Should NOT trigger
            mock_llm.assert_not_called()
            assert result == messages
        finally:
            await store.close()
