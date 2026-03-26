# Feature: smartclaw-p2a-production-services, Property 4: 不存在的 session 返回空结果
"""Property tests for sessions endpoints with non-existent session keys.

**Validates: Requirements 4.4**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.gateway.conftest import make_test_client

# Strategy: generate random session keys (printable ASCII, no slashes)
_session_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Property 4: 不存在的 session 返回空结果
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(_session_key_st)
def test_nonexistent_session_history_returns_empty_list(session_key: str) -> None:
    """GET /api/sessions/{key}/history returns empty list for unknown session."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get(f"/api/sessions/{session_key}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == session_key
        assert data["messages"] == []
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(_session_key_st)
def test_nonexistent_session_summary_returns_empty_string(session_key: str) -> None:
    """GET /api/sessions/{key}/summary returns empty string for unknown session."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get(f"/api/sessions/{session_key}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == session_key
        assert data["summary"] == ""
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(_session_key_st)
def test_nonexistent_session_no_error_status(session_key: str) -> None:
    """Neither history nor summary endpoint returns error status for unknown session."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        client, _, _, _ = make_test_client()
        with client:
            r1 = client.get(f"/api/sessions/{session_key}/history")
            r2 = client.get(f"/api/sessions/{session_key}/summary")
        assert r1.status_code < 400
        assert r2.status_code < 400
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
