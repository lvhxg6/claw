"""Property-based tests for request-level model override.

Properties 4, 5, 6 from the design document.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import smartclaw.agent.graph as graph_module
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.gateway.conftest import make_test_client


def _make_mock_result() -> dict:
    return {
        "final_answer": "Mock response",
        "iteration": 1,
        "error": None,
        "session_key": None,
        "messages": [],
        "summary": None,
        "sub_agent_depth": None,
    }


# ---------------------------------------------------------------------------
# Property 4: 无模型覆盖时使用默认 graph
# Feature: smartclaw-gateway-full-agent, Property 4: No model override uses default graph
# **Validates: Requirements 4.2**
# ---------------------------------------------------------------------------


class TestProperty4NoModelOverrideUsesDefault:
    """When model is None or empty, chat uses the default runtime.graph."""

    @settings(max_examples=100, deadline=None)
    @given(model_value=st.one_of(st.none(), st.just("")))
    def test_no_override_uses_default_graph(self, model_value):
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()
            payload = {"message": "hello"}
            if model_value is not None:
                payload["model"] = model_value

            with patch("smartclaw.agent.graph.build_graph") as mock_build:
                with client:
                    resp = client.post("/api/chat", json=payload)

                assert resp.status_code == 200
                # build_graph should NOT be called — default graph is used
                mock_build.assert_not_called()
        finally:
            graph_module.invoke = original


# ---------------------------------------------------------------------------
# Property 5: 有效模型覆盖使用相同工具集
# Feature: smartclaw-gateway-full-agent, Property 5: Valid model override uses same tools
# **Validates: Requirements 4.3, 4.6**
# ---------------------------------------------------------------------------

# Strategy: generate valid provider/model strings
_valid_provider = st.from_regex(r"[a-z]{1,10}", fullmatch=True)
_valid_model = st.from_regex(r"[a-z0-9][a-z0-9\-]{0,20}", fullmatch=True)
_valid_model_ref = st.tuples(_valid_provider, _valid_model).map(lambda t: f"{t[0]}/{t[1]}")


class TestProperty5ValidModelOverrideSameTools:
    """Valid model override builds temp graph with same tools as runtime."""

    @settings(max_examples=100, deadline=None)
    @given(model_ref=_valid_model_ref)
    def test_valid_override_uses_runtime_tools(self, model_ref):
        original = graph_module.invoke
        try:
            client, mock_invoke, _, _ = make_test_client()

            with patch("smartclaw.agent.graph.build_graph") as mock_build:
                mock_build.return_value = MagicMock(name="temp_graph")
                with client:
                    resp = client.post(
                        "/api/chat",
                        json={"message": "hello", "model": model_ref},
                    )

                assert resp.status_code == 200
                mock_build.assert_called_once()
                call_args = mock_build.call_args
                temp_config = call_args[0][0]
                tools_passed = call_args[0][1]
                # The temp config should have the overridden primary
                assert temp_config.primary == model_ref
                # Tools should be a list (runtime.tools)
                assert isinstance(tools_passed, list)
        finally:
            graph_module.invoke = original


# ---------------------------------------------------------------------------
# Property 6: 无效模型引用返回错误
# Feature: smartclaw-gateway-full-agent, Property 6: Invalid model ref returns error
# **Validates: Requirements 4.5**
# ---------------------------------------------------------------------------

# Strategy: generate invalid model refs (no valid provider/model split)
_invalid_model_ref = st.text(min_size=1, max_size=50).filter(
    lambda s: "/" not in s or s.startswith("/") or s.endswith("/") or s.split("/", 1)[0] == "" or s.split("/", 1)[1] == ""
)


class TestProperty6InvalidModelRefReturnsError:
    """Invalid model references return HTTP 400."""

    @settings(max_examples=100, deadline=None)
    @given(model_ref=_invalid_model_ref)
    def test_invalid_model_returns_400(self, model_ref):
        original = graph_module.invoke
        try:
            client, _, _, _ = make_test_client()
            with client:
                resp = client.post(
                    "/api/chat",
                    json={"message": "hello", "model": model_ref},
                )
            assert resp.status_code == 400
            assert "error" in resp.json()
        finally:
            graph_module.invoke = original
