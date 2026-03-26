# Feature: smartclaw-p2a-production-services, Property 2: Chat 响应完整性与自动 session_key
"""Property tests for chat endpoint response completeness and auto session_key.

**Validates: Requirements 2.2, 2.4**
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.gateway.conftest import make_test_client


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Property 2: Chat 响应完整性与自动 session_key
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(st.text(min_size=1, max_size=200))
def test_chat_response_has_all_required_fields(message: str) -> None:
    """For any valid message, POST /api/chat response contains all required fields."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, mock_invoke, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_key" in data
        assert "response" in data
        assert "iterations" in data
        assert "error" in data or data.get("error") is None
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(st.text(min_size=1, max_size=200))
def test_auto_session_key_is_valid_uuid(message: str) -> None:
    """When no session_key is provided, response session_key must be a valid UUID."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, mock_invoke, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.json()
        assert _is_valid_uuid(data["session_key"])
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(
    st.text(min_size=1, max_size=200),
    st.text(min_size=1, max_size=50),
)
def test_provided_session_key_preserved(message: str, session_key: str) -> None:
    """When session_key is provided, it must be echoed back in the response."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, mock_invoke, _, _ = make_test_client()
        with client:
            resp = client.post(
                "/api/chat",
                json={"message": message, "session_key": session_key},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == session_key
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
