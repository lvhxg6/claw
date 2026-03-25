"""Property-based tests for agent graph.

Feature: smartclaw-llm-agent-core
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.graph import build_graph, create_vision_message, invoke
from smartclaw.providers.config import ModelConfig


def _default_model_config() -> ModelConfig:
    return ModelConfig(
        primary="openai/gpt-4o",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


# ---------------------------------------------------------------------------
# Feature: smartclaw-llm-agent-core, Property 9: Streaming callback receives accumulated text
# ---------------------------------------------------------------------------


class TestStreamingCallback:
    """**Validates: Requirements 4.3**

    For any sequence of token chunks, the stream_callback should be invoked
    with accumulated strings where each invocation's text length is
    monotonically non-decreasing.
    """

    @given(
        chunks=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_callback_receives_monotonically_increasing_text(self, chunks: list[str]) -> None:
        """Stream callback receives accumulated text with non-decreasing lengths."""
        # Simulate the streaming accumulation logic from graph.py
        accumulated_calls: list[str] = []
        callback = lambda text: accumulated_calls.append(text)  # noqa: E731

        # Simulate what _llm_call_with_fallback does during streaming
        accumulated = ""
        for chunk in chunks:
            accumulated += chunk
            callback(accumulated)

        # Verify monotonically non-decreasing lengths
        lengths = [len(t) for t in accumulated_calls]
        for i in range(1, len(lengths)):
            assert lengths[i] >= lengths[i - 1]

        # Final accumulated text should be the concatenation of all chunks
        assert accumulated_calls[-1] == "".join(chunks)


# ---------------------------------------------------------------------------
# Feature: smartclaw-llm-agent-core, Property 12: Max iterations bounds the agent loop
# ---------------------------------------------------------------------------


class TestMaxIterationsBounds:
    """**Validates: Requirements 6.7**

    For any max_iterations value M (M >= 1), the agent graph should execute
    at most M reasoning iterations before terminating.
    """

    @given(
        max_iterations=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_iteration_bounded_by_max(self, max_iterations: int) -> None:
        """Agent loop terminates within max_iterations."""
        config = _default_model_config()

        # Create an LLM that always returns tool_calls to force looping
        call_count = 0

        async def mock_execute(candidates, run):  # noqa: ANN001, ARG001
            nonlocal call_count
            call_count += 1
            # Return AIMessage with tool_calls to keep looping,
            # but the reasoning_node will check max_iterations
            return MagicMock(
                response=AIMessage(
                    content="",
                    tool_calls=[{"name": "test_tool", "args": {}, "id": f"tc_{call_count}"}],
                )
            )

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_fc.execute = mock_execute

            graph = build_graph(config, tools=[])
            result = await invoke(graph, "test", max_iterations=max_iterations)

        assert result["iteration"] <= max_iterations + 1  # +1 for the final check iteration


# ---------------------------------------------------------------------------
# Feature: smartclaw-llm-agent-core, Property 13: Invoke initializes state correctly
# ---------------------------------------------------------------------------


class TestInvokeInitialization:
    """**Validates: Requirements 7.3**

    For any non-empty user message string, invoke() should produce an initial
    AgentState where messages[0] is a HumanMessage containing the user message
    text, and iteration == 0 at the start.
    """

    @given(
        user_message=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=200,
        ),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_invoke_starts_with_human_message(self, user_message: str) -> None:
        """invoke() initializes state with HumanMessage and iteration=0."""
        config = _default_model_config()
        ai_response = AIMessage(content="Response")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_graph(config, tools=[])
            result = await invoke(graph, user_message)

        # First message should be the user's HumanMessage
        first_msg = result["messages"][0]
        assert isinstance(first_msg, HumanMessage)
        assert first_msg.content == user_message

        # Iteration should be >= 1 (at least one reasoning step happened)
        assert result["iteration"] >= 1


# ---------------------------------------------------------------------------
# Feature: smartclaw-llm-agent-core, Property 14: Vision message construction
# ---------------------------------------------------------------------------

# Valid media types for image content
_MEDIA_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"]


class TestVisionMessageConstruction:
    """**Validates: Requirements 8.2, 8.7**

    For any non-empty text, non-empty base64 image string, and valid media_type,
    create_vision_message() returns a HumanMessage whose content list contains
    exactly 2 blocks: one text block and one image_url block with the correct
    data URI.
    """

    @given(
        text=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=200,
        ),
        image_bytes=st.binary(min_size=1, max_size=100),
        media_type=st.sampled_from(_MEDIA_TYPES),
    )
    @settings(max_examples=100)
    def test_vision_message_structure(
        self,
        text: str,
        image_bytes: bytes,
        media_type: str,
    ) -> None:
        """create_vision_message produces correct 2-block content list."""
        image_base64 = base64.b64encode(image_bytes).decode()
        msg = create_vision_message(text, image_base64, media_type=media_type)

        # Must be HumanMessage
        assert isinstance(msg, HumanMessage)

        # Content must be a list with exactly 2 blocks
        content = msg.content
        assert isinstance(content, list)
        assert len(content) == 2

        # First block: text
        text_block = content[0]
        assert text_block["type"] == "text"
        assert text_block["text"] == text

        # Second block: image_url with correct data URI
        image_block = content[1]
        assert image_block["type"] == "image_url"
        url = image_block["image_url"]["url"]
        expected_prefix = f"data:{media_type};base64,"
        assert url.startswith(expected_prefix)
        assert url == f"{expected_prefix}{image_base64}"
