"""Decision Trace Collector — module-level singleton for decision storage.

Stores :class:`DecisionRecord` instances grouped by ``session_key`` and
publishes ``decision.captured`` events via the Diagnostic Bus.

Usage::

    from smartclaw.observability import decision_collector
    from smartclaw.observability.decision_record import (
        DecisionRecord, DecisionType, _utc_now_iso,
    )

    record = DecisionRecord(
        timestamp=_utc_now_iso(),
        iteration=0,
        decision_type=DecisionType.TOOL_CALL,
        input_summary="user asked about weather",
        reasoning="I need to search for weather info",
        tool_calls=[{"tool_name": "web_search", "tool_args": {"query": "weather"}}],
        session_key="sess-1",
    )
    await decision_collector.add(record)
    decisions = decision_collector.get_decisions("sess-1")
    decision_collector.clear("sess-1")
"""

from __future__ import annotations

from smartclaw.observability.decision_record import DecisionRecord
from smartclaw.observability.logging import get_logger

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

logger = get_logger("observability.decision_collector")

_DEFAULT_KEY: str = "__default__"
_MAX_RECORDS_PER_SESSION: int = 200

# In-memory storage: session_key → list of DecisionRecord
_store: dict[str, list[DecisionRecord]] = {}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def add(record: DecisionRecord) -> None:
    """Store *record* and publish ``decision.captured`` via Diagnostic Bus.

    Records are grouped by ``record.session_key`` (falls back to
    ``_DEFAULT_KEY`` when *None*).  When a session exceeds
    ``_MAX_RECORDS_PER_SESSION`` the oldest records are discarded.
    """
    key = record.session_key or _DEFAULT_KEY

    if key not in _store:
        _store[key] = []
    _store[key].append(record)

    # Trim to cap when over limit
    if len(_store[key]) > _MAX_RECORDS_PER_SESSION:
        _store[key] = _store[key][-_MAX_RECORDS_PER_SESSION:]

    # Publish to Diagnostic Bus
    try:
        from smartclaw.observability import diagnostic_bus

        await diagnostic_bus.emit("decision.captured", record.to_dict())
    except Exception as exc:
        logger.error("decision_bus_publish_failed", error=str(exc))


def get_decisions(session_key: str) -> list[DecisionRecord]:
    """Return all records for *session_key*, sorted by timestamp ascending."""
    records = _store.get(session_key, [])
    return sorted(records, key=lambda r: r.timestamp)


def clear(session_key: str | None = None) -> None:
    """Clear records for *session_key*, or all records when *None*."""
    if session_key is None:
        _store.clear()
    else:
        _store.pop(session_key, None)
