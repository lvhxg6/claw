"""Unit tests for sessions endpoints.

Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from tests.gateway.conftest import make_test_client


def test_get_history_returns_empty_for_unknown_session() -> None:
    """GET /api/sessions/{key}/history returns empty list for unknown session. (Req 4.4)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.get_history = AsyncMock(return_value=[])
        with client:
            resp = client.get("/api/sessions/unknown-key/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == "unknown-key"
        assert data["messages"] == []
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_get_summary_returns_empty_for_unknown_session() -> None:
    """GET /api/sessions/{key}/summary returns empty string for unknown session. (Req 4.4)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.get_summary = AsyncMock(return_value="")
        with client:
            resp = client.get("/api/sessions/unknown-key/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == "unknown-key"
        assert data["summary"] == ""
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_delete_session_returns_deleted_true() -> None:
    """DELETE /api/sessions/{key} returns {deleted: true}. (Req 4.3)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.delete("/api/sessions/my-session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_get_history_returns_session_key_in_response() -> None:
    """GET /api/sessions/{key}/history echoes back the session_key. (Req 4.1)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get("/api/sessions/my-session-123/history")
        assert resp.status_code == 200
        assert resp.json()["session_key"] == "my-session-123"
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_get_summary_returns_session_key_in_response() -> None:
    """GET /api/sessions/{key}/summary echoes back the session_key. (Req 4.2)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get("/api/sessions/my-session-456/summary")
        assert resp.status_code == 200
        assert resp.json()["session_key"] == "my-session-456"
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_delete_session_calls_memory_store() -> None:
    """DELETE /api/sessions/{key} clears history and summary in memory store."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        with client:
            resp = client.delete("/api/sessions/clear-me")
        assert resp.status_code == 200
        mock_memory.set_history.assert_called_once()
        mock_memory.set_summary.assert_called_once()
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
