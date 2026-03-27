# Feature: llm-decision-observability, Property 6: 决策记录存储往返
# Feature: llm-decision-observability, Property 7: 决策记录时间戳升序不变量
# Feature: llm-decision-observability, Property 8: 每个 session 最多 200 条记录不变量
# Feature: llm-decision-observability, Property 10: 决策事件通过 Diagnostic Bus 发布
"""Property-based tests for DecisionTraceCollector.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 6: For any DecisionRecord and session_key, add() then get_decisions()
            should contain the record.
Property 7: get_decisions() returns records with monotonically non-decreasing
            timestamps.
Property 8: get_decisions() length never exceeds 200.
Property 10: add() triggers decision.captured event on diagnostic_bus.

**Validates: Requirements 4.1, 4.3, 4.5, 5.1, 11.2, 11.4**
"""

from __future__ import annotations

import asyncio
import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.observability import decision_collector, diagnostic_bus
from smartclaw.observability.decision_collector import (
    _MAX_RECORDS_PER_SESSION,
    add,
    clear,
    get_decisions,
)
from smartclaw.observability.decision_record import DecisionRecord, DecisionType

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_decision_type_st = st.sampled_from(list(DecisionType))

_tool_call_st = st.fixed_dictionaries(
    {
        "tool_name": st.text(min_size=1, max_size=32),
        "tool_args": st.fixed_dictionaries({}),
    }
)

_iso_timestamp_st = st.datetimes(
    min_value=datetime.datetime(2000, 1, 1),
    max_value=datetime.datetime(2099, 12, 31),
    timezones=st.just(datetime.timezone.utc),
).map(lambda dt: dt.isoformat())


@st.composite
def decision_record_st(draw: st.DrawFn) -> DecisionRecord:
    """Generate a valid DecisionRecord with constrained field sizes."""
    return DecisionRecord(
        timestamp=draw(_iso_timestamp_st),
        iteration=draw(st.integers(min_value=0, max_value=10_000)),
        decision_type=draw(_decision_type_st),
        input_summary=draw(st.text(max_size=512)),
        reasoning=draw(st.text(max_size=2048)),
        tool_calls=draw(st.lists(_tool_call_st, max_size=5)),
        target_agent=draw(st.one_of(st.none(), st.text(min_size=1, max_size=64))),
        session_key=draw(st.one_of(st.none(), st.text(min_size=1, max_size=64))),
    )


# ---------------------------------------------------------------------------
# Autouse fixture — clean collector and diagnostic_bus before/after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure a clean collector and diagnostic_bus state for every test."""
    clear()
    diagnostic_bus.clear()
    yield
    clear()
    diagnostic_bus.clear()


# ---------------------------------------------------------------------------
# Property 6: 决策记录存储往返
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 6: 决策记录存储往返
@given(record=decision_record_st())
@settings(max_examples=100, deadline=None)
def test_add_then_get_contains_record(record: DecisionRecord) -> None:
    """add() then get_decisions() should contain the record.

    **Validates: Requirements 4.1, 11.2**
    """
    clear()
    diagnostic_bus.clear()

    key = record.session_key or "__default__"
    asyncio.run(add(record))
    decisions = get_decisions(key)
    found = [d for d in decisions if d.to_dict() == record.to_dict()]
    assert len(found) >= 1, (
        f"Record not found in get_decisions('{key}'). "
        f"Got {len(decisions)} records."
    )


# ---------------------------------------------------------------------------
# Property 7: 决策记录时间戳升序不变量
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 7: 决策记录时间戳升序不变量
@given(records=st.lists(decision_record_st(), min_size=1, max_size=20))
@settings(max_examples=100, deadline=None)
def test_get_decisions_timestamps_non_decreasing(
    records: list[DecisionRecord],
) -> None:
    """get_decisions() returns records with monotonically non-decreasing timestamps.

    **Validates: Requirements 4.3, 11.4**
    """
    clear()
    diagnostic_bus.clear()

    # Force all records to the same session_key for meaningful assertion
    session_key = "prop7-session"
    loop = asyncio.new_event_loop()
    for r in records:
        # Create a copy with a fixed session_key
        patched = DecisionRecord(
            timestamp=r.timestamp,
            iteration=r.iteration,
            decision_type=r.decision_type,
            input_summary=r.input_summary,
            reasoning=r.reasoning,
            tool_calls=r.tool_calls,
            target_agent=r.target_agent,
            session_key=session_key,
        )
        loop.run_until_complete(add(patched))

    decisions = get_decisions(session_key)
    timestamps = [d.timestamp for d in decisions]
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i - 1], (
            f"Timestamp ordering violated at index {i}: "
            f"{timestamps[i - 1]!r} > {timestamps[i]!r}"
        )


# ---------------------------------------------------------------------------
# Property 8: 每个 session 最多 200 条记录不变量
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 8: 每个 session 最多 200 条记录不变量
@given(
    count=st.integers(min_value=1, max_value=300),
    record=decision_record_st(),
)
@settings(max_examples=100, deadline=None)
def test_max_records_per_session_invariant(
    count: int, record: DecisionRecord
) -> None:
    """get_decisions() length never exceeds 200.

    **Validates: Requirements 4.5**
    """
    clear()
    diagnostic_bus.clear()

    session_key = "prop8-session"
    loop = asyncio.new_event_loop()
    for i in range(count):
        patched = DecisionRecord(
            timestamp=record.timestamp,
            iteration=i,
            decision_type=record.decision_type,
            input_summary=record.input_summary,
            reasoning=record.reasoning,
            tool_calls=record.tool_calls,
            target_agent=record.target_agent,
            session_key=session_key,
        )
        loop.run_until_complete(add(patched))

    decisions = get_decisions(session_key)
    assert len(decisions) <= _MAX_RECORDS_PER_SESSION, (
        f"Expected at most {_MAX_RECORDS_PER_SESSION} records, "
        f"got {len(decisions)} after adding {count}."
    )


# ---------------------------------------------------------------------------
# Property 10: 决策事件通过 Diagnostic Bus 发布
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 10: 决策事件通过 Diagnostic Bus 发布
@given(record=decision_record_st())
@settings(max_examples=100, deadline=None)
def test_add_publishes_decision_captured_event(record: DecisionRecord) -> None:
    """add() triggers decision.captured event on diagnostic_bus.

    **Validates: Requirements 5.1**
    """
    clear()
    diagnostic_bus.clear()

    captured_events: list[dict] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        captured_events.append({"event_type": event_type, "payload": payload})

    diagnostic_bus.on("decision.captured", subscriber)
    try:
        asyncio.run(add(record))

        assert len(captured_events) == 1, (
            f"Expected exactly 1 event, got {len(captured_events)}"
        )
        assert captured_events[0]["event_type"] == "decision.captured"
        assert captured_events[0]["payload"] == record.to_dict()
    finally:
        diagnostic_bus.off("decision.captured", subscriber)
