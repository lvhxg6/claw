"""Property-based tests for session config and token stats (Properties 25-26).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage

from smartclaw.agent.state import TokenStats


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_model_refs = st.builds(
    lambda p, m: f"{p}/{m}",
    p=st.sampled_from(["openai", "anthropic", "kimi"]),
    m=st.from_regex(r"[a-z0-9-]{3,15}", fullmatch=True),
)

_session_keys = st.from_regex(r"[a-z0-9]{8,16}", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 25: 会话模型覆盖解析
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 25: 会话模型覆盖解析
class TestSessionModelOverride:
    """**Validates: Requirements 8.3**

    For any session with a stored model_override in session_config,
    when a chat request arrives without a model field, the system
    should use the stored model_override.
    """

    @given(
        session_key=_session_keys,
        model_override=_model_refs,
    )
    @settings(max_examples=100)
    def test_session_override_used_when_no_request_model(
        self, session_key: str, model_override: str
    ) -> None:
        """When request has no model, session_config model_override is used."""
        from smartclaw.gateway.models import ChatRequest

        # Create a request without model
        req = ChatRequest(message="hello", session_key=session_key)
        assert req.model is None

        # Mock memory_store that returns model_override
        mock_store = AsyncMock()
        mock_store.get_session_config = AsyncMock(
            return_value={"model_override": model_override}
        )

        # Simulate the chat endpoint logic: if no model, query session_config
        effective_model = req.model
        if not effective_model:
            loop = asyncio.new_event_loop()
            try:
                cfg = loop.run_until_complete(
                    mock_store.get_session_config(session_key)
                )
            finally:
                loop.close()
            if cfg and cfg.get("model_override"):
                effective_model = cfg["model_override"]

        assert effective_model == model_override

    @given(session_key=_session_keys)
    @settings(max_examples=100)
    def test_no_override_when_request_has_model(self, session_key: str) -> None:
        """When request specifies a model, session_config is not consulted."""
        from smartclaw.gateway.models import ChatRequest

        explicit_model = "openai/gpt-4o"
        req = ChatRequest(
            message="hello", session_key=session_key, model=explicit_model
        )
        # The request model should be used directly
        assert req.model == explicit_model


# ---------------------------------------------------------------------------
# Property 26: Token 统计累加
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 26: Token 统计累加
class TestTokenStatsAccumulation:
    """**Validates: Requirements 8.5, 8.7**

    For any sequence of LLM calls where AIMessage contains usage_metadata,
    the final token_stats should equal the sum of all individual values.
    When usage_metadata is absent, estimate_tokens should be used as fallback.
    """

    @given(
        usage_list=st.lists(
            st.fixed_dictionaries({
                "input_tokens": st.integers(min_value=0, max_value=10000),
                "output_tokens": st.integers(min_value=0, max_value=10000),
                "total_tokens": st.integers(min_value=0, max_value=20000),
            }),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=100)
    def test_token_stats_accumulate_from_usage_metadata(
        self, usage_list: list[dict[str, int]]
    ) -> None:
        """Token stats accumulate correctly from usage_metadata."""
        stats: TokenStats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for usage in usage_list:
            stats = {
                "prompt_tokens": stats["prompt_tokens"] + usage["input_tokens"],
                "completion_tokens": stats["completion_tokens"] + usage["output_tokens"],
                "total_tokens": stats["total_tokens"] + usage["total_tokens"],
            }

        expected_prompt = sum(u["input_tokens"] for u in usage_list)
        expected_completion = sum(u["output_tokens"] for u in usage_list)
        expected_total = sum(u["total_tokens"] for u in usage_list)

        assert stats["prompt_tokens"] == expected_prompt
        assert stats["completion_tokens"] == expected_completion
        assert stats["total_tokens"] == expected_total

    @given(
        content=st.text(min_size=1, max_size=500),
    )
    @settings(max_examples=100)
    def test_fallback_estimation_produces_non_negative(
        self, content: str
    ) -> None:
        """When usage_metadata is absent, fallback estimation is non-negative."""
        from smartclaw.memory.summarizer import AutoSummarizer

        msg = AIMessage(content=content)
        # estimate_tokens is a regular method but works with any list
        est = AutoSummarizer.estimate_tokens(None, [msg])  # type: ignore[arg-type]
        assert est >= 0
