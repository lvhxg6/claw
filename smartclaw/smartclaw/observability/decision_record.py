"""Decision Record — frozen dataclass for LLM decision tracing.

Captures each LLM decision step: tool calls, final answers, and supervisor
routing decisions.  Provides ``to_dict()`` / ``from_dict()`` round-trip
serialisation compatible with JSON and the Diagnostic Bus event payload.

Usage::

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
    )
    d = record.to_dict()
    restored = DecisionRecord.from_dict(d)
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class DecisionType(str, enum.Enum):
    """Type of decision made by the LLM or supervisor."""

    TOOL_CALL = "tool_call"
    FINAL_ANSWER = "final_answer"
    SUPERVISOR_ROUTE = "supervisor_route"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionRecord:
    """Immutable record of a single LLM decision step."""

    # Required fields
    timestamp: str
    iteration: int
    decision_type: DecisionType
    input_summary: str  # max 512 chars
    reasoning: str  # max 2048 chars

    # Optional fields
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    target_agent: str | None = None
    session_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        d = asdict(self)
        d["decision_type"] = self.decision_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionRecord:
        """Deserialise from a dictionary, validating required fields."""
        required = {
            "timestamp",
            "iteration",
            "decision_type",
            "input_summary",
            "reasoning",
        }
        missing = required - set(data.keys())
        if missing:
            raise ValueError(
                f"Missing required fields: {', '.join(sorted(missing))}"
            )
        data = dict(data)  # shallow copy to avoid mutating caller's dict
        data["decision_type"] = DecisionType(data["decision_type"])
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
