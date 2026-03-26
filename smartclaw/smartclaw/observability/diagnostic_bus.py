"""Diagnostic Event Bus — emit/on/off/clear module-level singleton.

Supported event types:
    tool.executed   — a tool finished execution
    llm.called      — an LLM call completed
    agent.run       — agent invocation lifecycle (phase: "start" | "end")
    session.started — a session was created
    session.ended   — a session was closed
    config.reloaded — configuration was hot-reloaded

Usage::

    from smartclaw.observability import diagnostic_bus

    async def my_subscriber(event_type: str, payload: dict) -> None:
        print(event_type, payload)

    diagnostic_bus.on("tool.executed", my_subscriber)
    await diagnostic_bus.emit("tool.executed", {"tool_name": "search", "duration_ms": 42})
    diagnostic_bus.off("tool.executed", my_subscriber)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

DiagnosticSubscriber = Callable[[str, dict], Awaitable[None]]

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_subscribers: dict[str, list[DiagnosticSubscriber]] = {}

_log = structlog.get_logger(component="diagnostic_bus")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def emit(event_type: str, payload: dict) -> None:
    """Dispatch *event_type* with *payload* to all registered subscribers.

    Each subscriber is called in registration order.  If a subscriber raises,
    the exception is caught and logged via structlog; remaining subscribers
    still receive the event.  If there are no subscribers the function returns
    immediately.
    """
    subscribers = _subscribers.get(event_type, [])
    for subscriber in list(subscribers):
        try:
            await subscriber(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "diagnostic_bus subscriber error",
                event_type=event_type,
                subscriber=repr(subscriber),
                exc_info=exc,
            )


def on(event_type: str, subscriber: DiagnosticSubscriber) -> None:
    """Register *subscriber* for *event_type*."""
    if event_type not in _subscribers:
        _subscribers[event_type] = []
    _subscribers[event_type].append(subscriber)


def off(event_type: str, subscriber: DiagnosticSubscriber) -> None:
    """Unregister *subscriber* from *event_type*.  Silent if not found."""
    try:
        _subscribers.get(event_type, []).remove(subscriber)
    except ValueError:
        pass


def clear() -> None:
    """Remove all subscribers from all event types (testing helper)."""
    _subscribers.clear()


def get_subscribers(event_type: str) -> list[DiagnosticSubscriber]:
    """Return a copy of the subscriber list for *event_type* (testing helper)."""
    return list(_subscribers.get(event_type, []))
