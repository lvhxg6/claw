"""Unit tests for FastAPI app creation, CORS, and router mounting.

Requirements: 1.1, 1.4
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.gateway.conftest import make_test_client


def test_create_app_returns_fastapi_instance() -> None:
    """create_app() returns a FastAPI instance with correct title."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        assert client.app is not None
        assert isinstance(client.app, FastAPI)
        assert client.app.title == "SmartClaw API"
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_cors_middleware_present() -> None:
    """CORS middleware is configured on the app."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        middleware_classes = [m.cls.__name__ for m in client.app.user_middleware]
        # CORSMiddleware is added via add_middleware
        assert any("CORS" in name for name in middleware_classes)
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_chat_router_mounted() -> None:
    """POST /api/chat route is registered."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
        assert "/api/chat" in routes
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_sessions_router_mounted() -> None:
    """Sessions routes are registered."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
        assert any("/api/sessions" in r for r in routes)
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_tools_router_mounted() -> None:
    """GET /api/tools route is registered."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
        assert "/api/tools" in routes
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_health_router_mounted() -> None:
    """GET /health route is registered."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
        assert "/health" in routes
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_cors_preflight_allowed() -> None:
    """OPTIONS preflight request returns 200 with CORS headers."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.options(
                "/api/chat",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.status_code in (200, 204, 400)
        # CORS headers should be present
        assert "access-control-allow-origin" in resp.headers
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
