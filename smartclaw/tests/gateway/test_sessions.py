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
    """DELETE /api/sessions/{key} deletes persisted session state."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        with client:
            resp = client.delete("/api/sessions/clear-me")
        assert resp.status_code == 200
        mock_memory.delete_session.assert_called_once_with("clear-me")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_delete_session_removes_attachments() -> None:
    """DELETE /api/sessions/{key} removes linked attachments before session deletion."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att-1",
                    "session_key": "clear-me",
                    "filename": "report.txt",
                    "media_type": "text/plain",
                    "kind": "text",
                    "storage_path": "/tmp/att-1_report.txt",
                    "size_bytes": 12,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "hello",
                    "extract_summary": "hello",
                    "error_message": "",
                    "created_at": "2026-03-27 10:00:00",
                    "updated_at": "2026-03-27 10:00:00",
                }
            ]
        )
        mock_memory.get_attachment = AsyncMock(
            return_value={
                "asset_id": "att-1",
                "session_key": "clear-me",
                "filename": "report.txt",
                "media_type": "text/plain",
                "kind": "text",
                "storage_path": "/tmp/att-1_report.txt",
                "size_bytes": 12,
                "sha256": "abc",
                "status": "uploaded",
                "extract_status": "success",
                "extract_text": "hello",
                "extract_summary": "hello",
                "error_message": "",
                "created_at": "2026-03-27 10:00:00",
                "updated_at": "2026-03-27 10:00:00",
            }
        )
        with client:
            resp = client.delete("/api/sessions/clear-me")
        assert resp.status_code == 200
        mock_memory.delete_attachment.assert_called_once_with("att-1")
        mock_memory.delete_session.assert_called_once_with("clear-me")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_delete_session_force_clears_attachment_metadata_on_attachment_delete_failure() -> None:
    """DELETE /api/sessions/{key} still clears attachment metadata if file deletion fails."""
    import smartclaw.agent.graph as graph_module
    from smartclaw.uploads.service import UploadService

    original = graph_module.invoke
    original_delete_attachment = UploadService.delete_attachment
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att-1",
                    "session_key": "clear-me",
                    "filename": "report.txt",
                    "media_type": "text/plain",
                    "kind": "text",
                    "storage_path": "/tmp/att-1_report.txt",
                    "size_bytes": 12,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "hello",
                    "extract_summary": "hello",
                    "error_message": "",
                    "created_at": "2026-03-27 10:00:00",
                    "updated_at": "2026-03-27 10:00:00",
                }
            ]
        )

        async def _boom(self, asset_id: str) -> bool:
            raise RuntimeError("unlink failed")

        UploadService.delete_attachment = _boom  # type: ignore[method-assign]

        with client:
            resp = client.delete("/api/sessions/clear-me")

        assert resp.status_code == 200
        mock_memory.delete_attachments_for_session.assert_called_once_with("clear-me")
        mock_memory.delete_session.assert_called_once_with("clear-me")
    finally:
        UploadService.delete_attachment = original_delete_attachment  # type: ignore[method-assign]
        graph_module.invoke = original  # type: ignore[assignment]


def test_list_sessions_returns_recent_items() -> None:
    """GET /api/sessions returns recent session metadata."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_sessions = AsyncMock(
            return_value=[
                {
                    "session_key": "sess-1",
                    "title": "基线检查任务",
                    "preview": "先检查再加固",
                    "updated_at": "2026-03-27 10:00:00",
                    "message_count": 4,
                    "model_override": "kimi/kimi-k2.5",
                }
            ]
        )
        with client:
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data == [
            {
                "session_key": "sess-1",
                "title": "基线检查任务",
                "preview": "先检查再加固",
                "updated_at": "2026-03-27 10:00:00",
                "message_count": 4,
                "model_override": "kimi/kimi-k2.5",
            }
        ]
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_get_session_stats_returns_estimates_and_last_token_stats() -> None:
    """GET /api/sessions/{key}/stats returns estimated context usage and last token stats."""
    import smartclaw.agent.graph as graph_module
    from langchain_core.messages import HumanMessage

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.get_history = AsyncMock(return_value=[HumanMessage(content="hello world")])
        mock_memory.get_summary = AsyncMock(return_value="summary text")
        mock_memory.list_attachments = AsyncMock(
            return_value=[
                {
                    "extract_text": "attachment extracted text",
                }
            ]
        )
        mock_memory.get_session_config = AsyncMock(
            return_value={
                "model_override": "kimi/kimi-k2.5",
                "config": {
                    "runtime_stats": {
                        "last_token_stats": {
                            "prompt_tokens": 123,
                            "completion_tokens": 45,
                            "total_tokens": 168,
                        }
                    }
                },
            }
        )
        with client:
            resp = client.get("/api/sessions/sess-1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == "sess-1"
        assert data["message_count"] == 1
        assert data["attachment_count"] == 1
        assert data["context_window"] > 0
        assert data["context_tokens_est"] > 0
        assert data["last_token_stats"]["total_tokens"] == 168
        assert data["provider_cache_supported"] is False
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
