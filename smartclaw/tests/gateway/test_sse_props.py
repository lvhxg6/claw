# Feature: smartclaw-p2a-production-services, Property 3: SSE 协议格式合规
"""Property tests for SSE protocol compliance.

**Validates: Requirements 3.7**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.gateway.conftest import make_test_client


# ---------------------------------------------------------------------------
# Property 3: SSE 协议格式合规
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(st.text(min_size=1, max_size=200))
def test_sse_response_content_type_is_event_stream(message: str) -> None:
    """POST /api/chat/stream must return Content-Type: text/event-stream."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": message})
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(st.text(min_size=1, max_size=200))
def test_sse_response_body_contains_data_lines(message: str) -> None:
    """SSE response body must contain 'data:' lines."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": message})
        assert resp.status_code == 200
        body = resp.text
        # SSE format: each event has "data:" lines
        assert "data:" in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
