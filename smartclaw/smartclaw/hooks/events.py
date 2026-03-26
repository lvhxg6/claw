"""Hook event types for the SmartClaw lifecycle hook system.

Each event is a frozen dataclass carrying context about a specific hook point.
The base ``HookEvent`` provides ``to_dict()`` / ``from_dict()`` for JSON
serialisation round-trips.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HookEvent:
    """Base hook event.

    Every subclass must set a default ``hook_point`` matching one of the
    eight valid hook points defined in ``hooks/registry.py``.
    """

    hook_point: str
    timestamp: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the event to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HookEvent:
        """Deserialise a dictionary into the correct ``HookEvent`` subclass.

        Dispatches on the ``hook_point`` value.  Raises ``ValueError`` when
        the hook point is unknown.
        """
        hook_point = data.get("hook_point")
        subclass = _HOOK_POINT_TO_CLASS.get(hook_point)  # type: ignore[arg-type]
        if subclass is None:
            raise ValueError(f"Unknown hook_point: {hook_point!r}")
        # Filter data keys to only those accepted by the target dataclass
        valid_fields = {f.name for f in subclass.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return subclass(**filtered)


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolBeforeEvent(HookEvent):
    """Emitted before a tool call is executed."""

    hook_point: str = "tool:before"
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_call_id: str = ""


@dataclass(frozen=True)
class ToolAfterEvent(HookEvent):
    """Emitted after a tool call completes (success or failure)."""

    hook_point: str = "tool:after"
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_call_id: str = ""
    result: str = ""
    duration_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentStartEvent(HookEvent):
    """Emitted when the Agent graph starts processing a user message."""

    hook_point: str = "agent:start"
    session_key: str | None = None
    user_message: str = ""
    tools_count: int = 0


@dataclass(frozen=True)
class AgentEndEvent(HookEvent):
    """Emitted when the Agent graph finishes processing."""

    hook_point: str = "agent:end"
    session_key: str | None = None
    final_answer: str | None = None
    iterations: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# LLM events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMBeforeEvent(HookEvent):
    """Emitted before an LLM call."""

    hook_point: str = "llm:before"
    model: str = ""
    message_count: int = 0
    has_tools: bool = False


@dataclass(frozen=True)
class LLMAfterEvent(HookEvent):
    """Emitted after an LLM call completes."""

    hook_point: str = "llm:after"
    model: str = ""
    has_tool_calls: bool = False
    duration_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Session events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionStartEvent(HookEvent):
    """Emitted when a session starts."""

    hook_point: str = "session:start"
    session_key: str = ""


@dataclass(frozen=True)
class SessionEndEvent(HookEvent):
    """Emitted when a session ends."""

    hook_point: str = "session:end"
    session_key: str = ""


# ---------------------------------------------------------------------------
# Dispatch map (must be defined after all subclasses)
# ---------------------------------------------------------------------------

_HOOK_POINT_TO_CLASS: dict[str, type[HookEvent]] = {
    "tool:before": ToolBeforeEvent,
    "tool:after": ToolAfterEvent,
    "agent:start": AgentStartEvent,
    "agent:end": AgentEndEvent,
    "llm:before": LLMBeforeEvent,
    "llm:after": LLMAfterEvent,
    "session:start": SessionStartEvent,
    "session:end": SessionEndEvent,
}
