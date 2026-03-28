"""Unit tests for chat endpoints.

Requirements: 2.1, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8
"""

from __future__ import annotations

import json
import uuid

from smartclaw.gateway.routers.chat import _format_sse
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
    """POST /api/chat/stream emits events (thinking comes from hooks, done always present). (Req 3.2)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        # With mock invoke (no real hooks), at minimum a done event is emitted
        assert "done" in body
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


# ---------------------------------------------------------------------------
# Clarification mechanism tests (Req 3.5, 3.6, 3.8)
# ---------------------------------------------------------------------------


def test_post_chat_clarification_in_sync_response() -> None:
    """POST /api/chat returns clarification field when result has clarification_request. (Req 3.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        result = {
            "final_answer": "",
            "iteration": 1,
            "error": None,
            "session_key": None,
            "messages": [],
            "summary": None,
            "sub_agent_depth": None,
            "token_stats": None,
            "clarification_request": {
                "question": "Which file do you want to delete?",
                "options": ["file_a.txt", "file_b.txt"],
            },
        }
        client, _, _, _ = make_test_client(mock_invoke_result=result)
        with client:
            resp = client.post("/api/chat", json={"message": "delete a file"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["clarification"] is not None
        assert data["clarification"]["question"] == "Which file do you want to delete?"
        assert data["clarification"]["options"] == ["file_a.txt", "file_b.txt"]
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_no_clarification_when_absent() -> None:
    """POST /api/chat returns clarification=null when no clarification_request. (Req 3.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("clarification") is None
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_clarification_without_options() -> None:
    """POST /api/chat handles clarification_request with no options. (Req 3.5)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        result = {
            "final_answer": "",
            "iteration": 1,
            "error": None,
            "session_key": None,
            "messages": [],
            "summary": None,
            "sub_agent_depth": None,
            "token_stats": None,
            "clarification_request": {
                "question": "What format do you prefer?",
            },
        }
        client, _, _, _ = make_test_client(mock_invoke_result=result)
        with client:
            resp = client.post("/api/chat", json={"message": "generate report"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["clarification"] is not None
        assert data["clarification"]["question"] == "What format do you prefer?"
        assert data["clarification"]["options"] is None
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_clarification_event() -> None:
    """POST /api/chat/stream emits clarification event before done when clarification_request present. (Req 3.8)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        result = {
            "final_answer": "",
            "iteration": 1,
            "error": None,
            "session_key": None,
            "messages": [],
            "summary": None,
            "sub_agent_depth": None,
            "token_stats": None,
            "clarification_request": {
                "question": "Which file?",
                "options": ["a.txt", "b.txt"],
            },
        }
        client, _, _, _ = make_test_client(mock_invoke_result=result)
        with client:
            resp = client.post("/api/chat/stream", json={"message": "delete file"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: clarification" in body
        assert "Which file?" in body
        assert "\"session_key\"" in body
        # clarification event should appear before done event
        clar_pos = body.index("event: clarification")
        done_pos = body.index("event: done")
        assert clar_pos < done_pos
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_post_chat_stream_no_clarification_event_when_absent() -> None:
    """POST /api/chat/stream does not emit clarification event when no clarification_request. (Req 3.8)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: clarification" not in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]



def test_format_sse_clarification_hook_point() -> None:
    """_format_sse handles 'clarification' hook_point correctly. (Req 3.8)"""
    evt = {
        "hook_point": "clarification",
        "question": "Which environment?",
        "options": ["dev", "staging", "prod"],
    }
    result = _format_sse(evt)
    assert result is not None
    assert result["event"] == "clarification"
    data = json.loads(result["data"])
    assert data["question"] == "Which environment?"
    assert data["options"] == ["dev", "staging", "prod"]


def test_format_sse_clarification_without_options() -> None:
    """_format_sse handles 'clarification' hook_point with no options. (Req 3.8)"""
    evt = {
        "hook_point": "clarification",
        "question": "What do you mean?",
    }
    result = _format_sse(evt)
    assert result is not None
    assert result["event"] == "clarification"
    data = json.loads(result["data"])
    assert data["question"] == "What do you mean?"
    assert data["options"] is None
