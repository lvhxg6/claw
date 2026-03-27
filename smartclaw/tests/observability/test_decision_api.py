"""Unit tests for Decision SSE endpoint and REST API.

Tests cover:
- GET /api/debug/decision-events SSE endpoint registration
- GET /api/sessions/{session_key}/decisions REST endpoint
- Empty session returns empty array
- Populated session returns serialized records

Requirements: 6.1-6.5, 11.1-11.4
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from smartclaw.observability import decision_collector
from smartclaw.observability.decision_record import DecisionRecord, DecisionType, _utc_now_iso
from tests.gateway.conftest import make_test_client


def _make_record(session_key: str = "test-sess", iteration: int = 0) -> DecisionRecord:
    return DecisionRecord(
        timestamp=_utc_now_iso(),
        iteration=iteration,
        decision_type=DecisionType.TOOL_CALL,
        input_summary="user asked about weather",
        reasoning="I need to search for weather info",
        tool_calls=[{"tool_name": "web_search", "tool_args": {"query": "weather"}}],
        session_key=session_key,
    )


class TestDecisionRestAPI:
    """Tests for GET /api/sessions/{session_key}/decisions."""

    def setup_method(self):
        decision_collector.clear()

    def teardown_method(self):
        decision_collector.clear()

    def test_empty_session_returns_empty_list(self) -> None:
        """Nonexistent session_key returns empty JSON array."""
        import smartclaw.agent.graph as graph_module
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.get("/api/sessions/nonexistent/decisions")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            graph_module.invoke = original  # type: ignore[assignment]

    def test_returns_stored_decisions(self) -> None:
        """Stored decisions are returned as serialized dicts."""
        import asyncio
        import smartclaw.agent.graph as graph_module
        original = graph_module.invoke

        record = _make_record(session_key="sess-abc", iteration=1)
        asyncio.run(decision_collector.add(record))

        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.get("/api/sessions/sess-abc/decisions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["decision_type"] == "tool_call"
            assert data[0]["iteration"] == 1
            assert data[0]["session_key"] == "sess-abc"
        finally:
            graph_module.invoke = original  # type: ignore[assignment]

    def test_returns_multiple_decisions_ordered(self) -> None:
        """Multiple decisions returned in timestamp ascending order."""
        import asyncio
        import smartclaw.agent.graph as graph_module
        original = graph_module.invoke

        for i in range(3):
            record = _make_record(session_key="sess-multi", iteration=i)
            asyncio.run(decision_collector.add(record))

        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.get("/api/sessions/sess-multi/decisions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            # Verify ascending order by iteration
            iterations = [d["iteration"] for d in data]
            assert iterations == [0, 1, 2]
        finally:
            graph_module.invoke = original  # type: ignore[assignment]


class TestDecisionSSEEndpoint:
    """Tests for GET /api/debug/decision-events route registration."""

    def test_decision_events_route_registered(self) -> None:
        """The /api/debug/decision-events route is registered via create_app."""
        from smartclaw.gateway.app import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]
        assert "/api/debug/decision-events" in routes
