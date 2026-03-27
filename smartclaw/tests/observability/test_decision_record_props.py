# Feature: llm-decision-observability, Property 1: DecisionRecord 序列化往返一致性
# Feature: llm-decision-observability, Property 2: JSON 序列化往返一致性
# Feature: llm-decision-observability, Property 3: from_dict 缺少必填字段时抛出 ValueError
"""Property-based tests for DecisionRecord serialisation.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 1: For any valid DecisionRecord r, from_dict(r.to_dict()).to_dict() == r.to_dict().
Property 2: For any valid DecisionRecord r, json.loads(json.dumps(r.to_dict())) == r.to_dict().
Property 3: For any dict missing at least one required field, from_dict raises ValueError.

**Validates: Requirements 1.5, 9.1, 9.2, 9.3, 9.4**
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
    min_value=__import__("datetime").datetime(2000, 1, 1),
    max_value=__import__("datetime").datetime(2099, 12, 31),
    timezones=st.just(__import__("datetime").timezone.utc),
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
# Property 1: DecisionRecord 序列化往返一致性
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 1: DecisionRecord 序列化往返一致性
@given(record=decision_record_st())
@settings(max_examples=100, deadline=None)
def test_to_dict_from_dict_roundtrip(record: DecisionRecord) -> None:
    """from_dict(r.to_dict()).to_dict() == r.to_dict() for any valid record.

    **Validates: Requirements 1.5, 9.3**
    """
    d = record.to_dict()
    restored = DecisionRecord.from_dict(d)
    assert restored.to_dict() == d


# ---------------------------------------------------------------------------
# Property 2: JSON 序列化往返一致性
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 2: JSON 序列化往返一致性
@given(record=decision_record_st())
@settings(max_examples=100, deadline=None)
def test_json_roundtrip(record: DecisionRecord) -> None:
    """json.loads(json.dumps(r.to_dict())) == r.to_dict() for any valid record.

    **Validates: Requirements 9.1, 9.2**
    """
    d = record.to_dict()
    assert json.loads(json.dumps(d)) == d


# ---------------------------------------------------------------------------
# Property 3: from_dict 缺少必填字段时抛出 ValueError
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ["timestamp", "iteration", "decision_type", "input_summary", "reasoning"]


# Feature: llm-decision-observability, Property 3: from_dict 缺少必填字段时抛出 ValueError
@given(
    record=decision_record_st(),
    fields_to_remove=st.lists(
        st.sampled_from(_REQUIRED_FIELDS), min_size=1, unique=True,
    ),
)
@settings(max_examples=100, deadline=None)
def test_from_dict_missing_required_raises(
    record: DecisionRecord, fields_to_remove: list[str]
) -> None:
    """from_dict raises ValueError when any required field is missing.

    **Validates: Requirements 9.4**
    """
    d = record.to_dict()
    for f in fields_to_remove:
        d.pop(f, None)

    with pytest.raises(ValueError, match="Missing required fields"):
        DecisionRecord.from_dict(d)
