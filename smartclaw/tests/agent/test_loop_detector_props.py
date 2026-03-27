"""Property-based tests for LoopDetector and loop detection integration.

Feature: deerflow-advantages-absorption
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.loop_detector import LoopDetector, LoopStatus
from smartclaw.agent.nodes import action_node
from smartclaw.agent.state import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: object) -> AgentState:
    defaults: dict = {
        "messages": [],
        "iteration": 0,
        "max_iterations": 50,
        "final_answer": None,
        "error": None,
        "session_key": None,
        "summary": None,
        "sub_agent_depth": None,
        "token_stats": None,
        "clarification_request": None,
    }
    defaults.update(overrides)
    return defaults  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# JSON-serializable leaf values (no bytes, no nan/inf)
_json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=50),
)

# Recursive JSON-serializable values (dicts, lists, leaves)
_json_value = st.recursive(
    _json_leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=15,
)

# Tool args: dict of JSON-serializable values
_tool_args_st = st.dictionaries(st.text(max_size=20), _json_value, max_size=5)

# Tool name: non-empty text
_tool_name_st = st.text(min_size=1, max_size=50)

# Tool call entry: (name, args) pair
_tool_call_st = st.tuples(_tool_name_st, _tool_args_st)

# Sequence of tool calls
_tool_call_seq_st = st.lists(_tool_call_st, min_size=1, max_size=50)

_HEX_RE = re.compile(r"^[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 3: ToolCallHash 确定性
# ---------------------------------------------------------------------------


class TestToolCallHashDeterminism:
    """**Validates: Requirements 4.2**

    For any tool_name (str) and tool_args (dict of JSON-serializable values),
    compute_hash returns the same result for same inputs, is 16 chars hex,
    and equals hashlib.sha256(json.dumps({"name": tool_name, "args": tool_args},
    sort_keys=True).encode()).hexdigest()[:16].
    """

    @given(tool_name=_tool_name_st, tool_args=_tool_args_st)
    @settings(max_examples=100)
    def test_deterministic_and_correct(self, tool_name: str, tool_args: dict) -> None:
        h1 = LoopDetector.compute_hash(tool_name, tool_args)
        h2 = LoopDetector.compute_hash(tool_name, tool_args)

        # (a) Same inputs → same output (deterministic)
        assert h1 == h2

        # (b) 16-char hex string
        assert _HEX_RE.match(h1) is not None, f"Expected 16-char hex, got {h1!r}"

        # (c) Matches reference implementation
        expected_payload = json.dumps(
            {"name": tool_name, "args": tool_args}, sort_keys=True
        )
        expected = hashlib.sha256(expected_payload.encode()).hexdigest()[:16]
        assert h1 == expected



# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 4: 滑动窗口有界性
# ---------------------------------------------------------------------------


class TestSlidingWindowBoundedness:
    """**Validates: Requirements 4.3**

    For any LoopDetector (random window_size 1-100) and any sequence of tool
    calls, the internal window length never exceeds window_size.
    """

    @given(
        window_size=st.integers(min_value=1, max_value=100),
        calls=_tool_call_seq_st,
    )
    @settings(max_examples=100)
    def test_window_never_exceeds_size(
        self, window_size: int, calls: list[tuple[str, dict]]
    ) -> None:
        ld = LoopDetector(window_size=window_size, warn_threshold=50, stop_threshold=100)
        for name, args in calls:
            ld.record(name, args)
            assert len(ld._window) <= window_size


# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 5: 循环检测阈值正确性
# ---------------------------------------------------------------------------


class TestLoopDetectionThresholdCorrectness:
    """**Validates: Requirements 4.4, 4.5**

    For any LoopDetector (random warn_threshold < stop_threshold) and any
    tool call sequence, record() returns OK when count < warn, WARN when
    warn <= count < stop, STOP when count >= stop.
    """

    @given(
        warn_threshold=st.integers(min_value=2, max_value=10),
        gap=st.integers(min_value=1, max_value=10),
        calls=_tool_call_seq_st,
    )
    @settings(max_examples=100)
    def test_status_matches_count_thresholds(
        self,
        warn_threshold: int,
        gap: int,
        calls: list[tuple[str, dict]],
    ) -> None:
        stop_threshold = warn_threshold + gap
        # Use a large window so eviction doesn't interfere with counting
        window_size = len(calls) + 10
        ld = LoopDetector(
            window_size=window_size,
            warn_threshold=warn_threshold,
            stop_threshold=stop_threshold,
        )

        for name, args in calls:
            status = ld.record(name, args)
            h = LoopDetector.compute_hash(name, args)
            count = ld._window.count(h)

            if count >= stop_threshold:
                assert status == LoopStatus.STOP, (
                    f"Expected STOP for count={count}, got {status}"
                )
            elif count >= warn_threshold:
                assert status == LoopStatus.WARN, (
                    f"Expected WARN for count={count}, got {status}"
                )
            else:
                assert status == LoopStatus.OK, (
                    f"Expected OK for count={count}, got {status}"
                )


# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 6: action_node 循环检测集成
# ---------------------------------------------------------------------------


class _EchoTool:
    """Minimal fake tool that returns its input as a string."""

    name: str = "echo"

    async def ainvoke(self, args: dict) -> str:
        return f"echo: {args}"


class TestActionNodeLoopDetectionIntegration:
    """**Validates: Requirements 4.7**

    For any AIMessage with repeated tool calls and a LoopDetector with low
    thresholds, when action_node processes them, the result dict contains
    error when stop threshold is reached.
    """

    @given(
        repeat_count=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=100)
    async def test_stop_sets_error_on_repeated_calls(
        self, repeat_count: int
    ) -> None:
        stop_threshold = 2
        warn_threshold = 1

        tool_calls = [
            {"name": "echo", "args": {"x": "same"}, "id": f"tc_{i}"}
            for i in range(repeat_count)
        ]

        ai_msg = AIMessage(content="", tool_calls=tool_calls)
        state = _make_state(messages=[HumanMessage(content="hi"), ai_msg])

        ld = LoopDetector(
            window_size=100,
            warn_threshold=warn_threshold,
            stop_threshold=stop_threshold,
        )
        echo_tool = _EchoTool()

        result = await action_node(
            state,
            tools_by_name={"echo": echo_tool},  # type: ignore[arg-type]
            loop_detector=ld,
        )

        # With stop_threshold=2 and repeat_count>=2, the second identical
        # call should trigger STOP → error must be set.
        assert "error" in result
        assert result["error"] is not None
        assert "loop" in result["error"].lower() or "Loop" in result["error"]
