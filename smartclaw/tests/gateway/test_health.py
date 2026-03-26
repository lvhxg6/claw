"""Unit tests for health and ready endpoints.

Requirements: 5.2, 5.3
"""

from __future__ import annotations

from tests.gateway.conftest import make_test_client


def test_health_endpoint_returns_200() -> None:
    """GET /health returns 200 with status/version/tools_count. (Req 5.2)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "tools_count" in data
        assert isinstance(data["tools_count"], int)
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_health_tools_count_matches_registry() -> None:
    """GET /health tools_count matches number of registered tools."""
    from unittest.mock import MagicMock

    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        # Create 3 mock tools
        tools = []
        for i in range(3):
            t = MagicMock()
            t.name = f"tool_{i}"
            t.description = f"desc_{i}"
            tools.append(t)

        client, _, _, registry = make_test_client(tools=tools)
        with client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["tools_count"] == 3
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_ready_endpoint_returns_200_when_ready() -> None:
    """GET /ready returns 200 when app is ready. (Req 5.3)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client(ready=True)
        with client:
            resp = client.get("/ready")
        assert resp.status_code == 200
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_ready_endpoint_returns_503_when_not_ready() -> None:
    """GET /ready returns 503 when app is not ready. (Req 5.3)"""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client(ready=False)
        with client:
            resp = client.get("/ready")
        assert resp.status_code == 503
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_health_version_is_string() -> None:
    """GET /health version field is a non-empty string."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke
    try:
        client, _, _, _ = make_test_client()
        with client:
            resp = client.get("/health")
        assert resp.status_code == 200
        version = resp.json()["version"]
        assert isinstance(version, str)
        assert len(version) > 0
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
