"""Unit tests for vision message construction and multimodal support.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
"""

from __future__ import annotations

import base64

from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.graph import create_vision_message
from smartclaw.agent.state import AgentState

# ---------------------------------------------------------------------------
# create_vision_message tests (Requirement 8.2, 8.7)
# ---------------------------------------------------------------------------


class TestCreateVisionMessage:
    """Test create_vision_message output structure."""

    def test_returns_human_message(self) -> None:
        msg = create_vision_message("Describe this", "aGVsbG8=")
        assert isinstance(msg, HumanMessage)

    def test_content_is_list(self) -> None:
        msg = create_vision_message("Describe this", "aGVsbG8=")
        assert isinstance(msg.content, list)

    def test_content_has_two_blocks(self) -> None:
        msg = create_vision_message("Describe this", "aGVsbG8=")
        assert len(msg.content) == 2

    def test_first_block_is_text(self) -> None:
        msg = create_vision_message("Describe this", "aGVsbG8=")
        block = msg.content[0]
        assert block["type"] == "text"
        assert block["text"] == "Describe this"

    def test_second_block_is_image_url(self) -> None:
        msg = create_vision_message("Describe this", "aGVsbG8=")
        block = msg.content[1]
        assert block["type"] == "image_url"
        assert "image_url" in block

    def test_image_url_contains_data_uri(self) -> None:
        msg = create_vision_message("Describe", "aGVsbG8=", media_type="image/png")
        url = msg.content[1]["image_url"]["url"]
        assert url == "data:image/png;base64,aGVsbG8="

    def test_custom_media_type(self) -> None:
        msg = create_vision_message("Describe", "aGVsbG8=", media_type="image/jpeg")
        url = msg.content[1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_default_media_type_is_png(self) -> None:
        msg = create_vision_message("Describe", "aGVsbG8=")
        url = msg.content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_real_base64_image(self) -> None:
        """Test with actual base64-encoded data."""
        raw = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
        b64 = base64.b64encode(raw).decode()
        msg = create_vision_message("What is this?", b64)
        url = msg.content[1]["image_url"]["url"]
        assert b64 in url


# ---------------------------------------------------------------------------
# Mixed content in AgentState (Requirement 8.3)
# ---------------------------------------------------------------------------


class TestMixedContentState:
    """Test that AgentState supports messages with mixed content types."""

    def test_state_accepts_vision_message(self) -> None:
        vision_msg = create_vision_message("Describe", "aGVsbG8=")
        state: AgentState = {
            "messages": [vision_msg],
            "iteration": 0,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
        }
        assert len(state["messages"]) == 1
        assert isinstance(state["messages"][0].content, list)

    def test_state_mixes_text_and_vision(self) -> None:
        text_msg = HumanMessage(content="Hello")
        vision_msg = create_vision_message("Describe", "aGVsbG8=")
        ai_msg = AIMessage(content="I see an image")
        state: AgentState = {
            "messages": [text_msg, vision_msg, ai_msg],
            "iteration": 2,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
        }
        assert len(state["messages"]) == 3
        assert isinstance(state["messages"][0].content, str)
        assert isinstance(state["messages"][1].content, list)
        assert isinstance(state["messages"][2].content, str)
