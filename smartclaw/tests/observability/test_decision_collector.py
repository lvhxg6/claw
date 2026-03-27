"""Unit tests for decision_collector module."""

from __future__ import annotations

import pytest

from smartclaw.observability.decision_collector import (
    _DEFAULT_KEY,
    _MAX_RECORDS_PER_SESSION,
    add,
    clear,
    get_decisions,
)
from smartclaw.observability.decision_record import (
    DecisionRecord,
    DecisionType,
    _utc_now_iso,
)


@pytest.fixture(autouse=True)
def _clean_store():
    """Ensure a clean collector state for every test."""
    clear()
    yield
    clear()


def _make_record(
    *,
    session_key: str | None = "test-session",
    decision_type: DecisionType = DecisionType.TOOL_CALL,
    iteration: int = 0,
    timestamp: str | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        timestamp=timestamp or _utc_now_iso(),
        iteration=iteration,
        decision_type=decision_type,
        input_summary="test input",
        reasoning="test reasoning",
        session_key=session_key,
    )


# ---- add + get_decisions round-trip ------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_decisions():
    """Records added via add() are retrievable via get_decisions()."""
    rec = _make_record()
    await add(rec)
    decisions = get_decisions("test-session")
    assert len(decisions) == 1
    assert decisions[0] is rec


# ---- default key -------------------------------------------------------


@pytest.mark.asyncio
async def test_default_key_when_session_key_is_none():
    """Records without session_key use _DEFAULT_KEY."""
    rec = _make_record(session_key=None)
    await add(rec)
    assert get_decisions(_DEFAULT_KEY) == [rec]
    assert get_decisions("test-session") == []


# ---- clear specific session --------------------------------------------


@pytest.mark.asyncio
async def test_clear_specific_session():
    """clear(session_key) removes only that session."""
    await add(_make_record(session_key="a"))
    await add(_make_record(session_key="b"))
    clear("a")
    assert get_decisions("a") == []
    assert len(get_decisions("b")) == 1


# ---- clear all ---------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_all():
    """clear(None) removes all sessions."""
    await add(_make_record(session_key="a"))
    await add(_make_record(session_key="b"))
    clear()
    assert get_decisions("a") == []
    assert get_decisions("b") == []


# ---- max records cap ---------------------------------------------------


@pytest.mark.asyncio
async def test_max_records_per_session():
    """Exceeding _MAX_RECORDS_PER_SESSION keeps only the newest records."""
    for i in range(_MAX_RECORDS_PER_SESSION + 50):
        await add(_make_record(iteration=i))
    decisions = get_decisions("test-session")
    assert len(decisions) == _MAX_RECORDS_PER_SESSION
    # The oldest 50 should have been discarded
    assert decisions[0].iteration == 50


# ---- timestamp ordering ------------------------------------------------


@pytest.mark.asyncio
async def test_get_decisions_sorted_by_timestamp():
    """get_decisions returns records sorted by timestamp ascending."""
    await add(_make_record(timestamp="2024-01-01T00:00:03+00:00", iteration=3))
    await add(_make_record(timestamp="2024-01-01T00:00:01+00:00", iteration=1))
    await add(_make_record(timestamp="2024-01-01T00:00:02+00:00", iteration=2))
    decisions = get_decisions("test-session")
    timestamps = [d.timestamp for d in decisions]
    assert timestamps == sorted(timestamps)


# ---- nonexistent session returns empty list ----------------------------


def test_get_decisions_nonexistent_session():
    """Querying a session that doesn't exist returns an empty list."""
    assert get_decisions("does-not-exist") == []
