"""Unit tests for chat endpoints.

Requirements: 2.1, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import json
import uuid

from tests.gateway.conftest import make_test_client


def test_post_chat_normal_response() -> None:
    """POST /api/chat returns 200 with all required fields. (Req 2.1, 2.3, 2.4)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_key" in data
        assert "response" in data
        assert "iterations" in data
        assert data["response"] == "Mock response"
        assert data["iterations"] == 1
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_auto_generates_uuid_session_key() -> None:
    """POST /api/chat without session_key generates a valid UUID. (Req 2.4)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        session_key = resp.json()["session_key"]
        uuid.UUID(session_key)  # raises if not valid UUID
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_preserves_provided_session_key() -> None:
    """POST /api/chat echoes back the provided session_key. (Req 2.4)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post(
                "/api/chat",
                json={"message": "hello", "session_key": "my-session"},
            )
        assert resp.status_code == 200
        assert resp.json()["session_key"] == "my-session"
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_agent_exception_returns_500() -> None:
    """POST /api/chat returns HTTP 500 when Agent Graph raises. (Req 2.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client(invoke_side_effect=RuntimeError("LLM failure"))
        with client:
            resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_empty_message_returns_422() -> None:
    """POST /api/chat with empty message returns 422 validation error. (Req 1.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 422
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_returns_event_stream() -> None:
    """POST /api/chat/stream returns text/event-stream content type. (Req 3.7)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_contains_done_event() -> None:
    """POST /api/chat/stream emits a 'done' event. (Req 3.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: done" in body or "data:" in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_contains_thinking_event() -> None:
    """POST /api/chat/stream emits a 'thinking' event. (Req 3.2)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        assert "thinking" in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_error_event_on_exception() -> None:
    """POST /api/chat/stream emits 'error' event when invoke raises. (Req 3.6)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client(invoke_side_effect=RuntimeError("boom"))
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        assert "error" in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
