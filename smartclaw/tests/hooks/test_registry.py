"""Unit tests for the Hook registry.

Tests cover:
- register with invalid hook_point raises ValueError (Req 9.1)
- trigger with no handlers returns immediately (no error) (Req 9.4)
- clear() removes all handlers (Req 9.6)
- unregister of non-existent handler is silent

Requirements: 9.1, 9.4, 9.6
"""

from __future__ import annotations

import asyncio

import pytest

import smartclaw.hooks.registry as registry
from smartclaw.hooks.events import AgentStartEvent, HookEvent


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def setup_function():
    registry.clear()


def teardown_function():
    registry.clear()


# ---------------------------------------------------------------------------
# register: invalid hook_point raises ValueError
# ---------------------------------------------------------------------------


def test_register_invalid_hook_point_raises_value_error() -> None:
    """Registering with an invalid hook_point raises ValueError. (Req 9.1)"""
    async def handler(event: HookEvent) -> None:
        pass

    with pytest.raises(ValueError, match="Invalid hook_point"):
        registry.register("invalid:point", handler)


def test_register_all_valid_hook_points_succeeds() -> None:
    """All 8 valid hook points can be registered without error."""
    async def handler(event: HookEvent) -> None:
        pass

    for hp in registry.VALID_HOOK_POINTS:
        registry.register(hp, handler)  # should not raise


# ---------------------------------------------------------------------------
# trigger: no handlers returns immediately
# ---------------------------------------------------------------------------


def test_trigger_with_no_handlers_does_not_raise() -> None:
    """trigger on a hook_point with no handlers returns immediately. (Req 9.4)"""
    event = AgentStartEvent()
    _run(registry.trigger("agent:start", event))  # must not raise


def test_trigger_unknown_hook_point_does_not_raise() -> None:
    """trigger on a hook_point that was never registered does not raise."""
    event = AgentStartEvent()
    _run(registry.trigger("agent:start", event))  # no handlers registered


# ---------------------------------------------------------------------------
# clear: removes all handlers
# ---------------------------------------------------------------------------


def test_clear_removes_all_handlers() -> None:
    """clear() removes all registered handlers. (Req 9.6)"""
    called: list[str] = []

    async def handler(event: HookEvent) -> None:
        called.append("called")

    for hp in registry.VALID_HOOK_POINTS:
        registry.register(hp, handler)

    registry.clear()

    event = AgentStartEvent()
    _run(registry.trigger("agent:start", event))
    assert called == []


def test_clear_then_register_works() -> None:
    """After clear(), new registrations work normally."""
    called: list[str] = []

    async def handler(event: HookEvent) -> None:
        called.append("ok")

    registry.register("agent:start", handler)
    registry.clear()
    registry.register("agent:start", handler)

    event = AgentStartEvent()
    _run(registry.trigger("agent:start", event))
    assert called == ["ok"]


# ---------------------------------------------------------------------------
# unregister: non-existent handler is silent
# ---------------------------------------------------------------------------


def test_unregister_nonexistent_handler_is_silent() -> None:
    """Unregistering a handler that was never registered does not raise."""
    async def handler(event: HookEvent) -> None:
        pass

    # Should not raise even though handler was never registered
    registry.unregister("agent:start", handler)


def test_unregister_from_empty_hook_point_is_silent() -> None:
    """Unregistering from a hook_point with no handlers does not raise."""
    async def handler(event: HookEvent) -> None:
        pass

    registry.unregister("tool:before", handler)  # no handlers at all


# ---------------------------------------------------------------------------
# register + trigger: basic integration
# ---------------------------------------------------------------------------


def test_register_and_trigger_calls_handler() -> None:
    """Registered handler is called on trigger."""
    called: list[HookEvent] = []

    async def handler(event: HookEvent) -> None:
        called.append(event)

    registry.register("agent:start", handler)
    event = AgentStartEvent(user_message="hello")
    _run(registry.trigger("agent:start", event))

    assert len(called) == 1
    assert called[0] is event


def test_multiple_handlers_called_in_order() -> None:
    """Multiple handlers on same hook_point are called in registration order."""
    order: list[int] = []

    async def h1(event: HookEvent) -> None:
        order.append(1)

    async def h2(event: HookEvent) -> None:
        order.append(2)

    async def h3(event: HookEvent) -> None:
        order.append(3)

    registry.register("agent:start", h1)
    registry.register("agent:start", h2)
    registry.register("agent:start", h3)

    _run(registry.trigger("agent:start", AgentStartEvent()))
    assert order == [1, 2, 3]


def test_error_in_handler_does_not_prevent_others() -> None:
    """A handler that raises does not prevent subsequent handlers from running."""
    called: list[str] = []

    async def bad_handler(event: HookEvent) -> None:
        raise RuntimeError("boom")

    async def good_handler(event: HookEvent) -> None:
        called.append("good")

    registry.register("agent:start", bad_handler)
    registry.register("agent:start", good_handler)

    _run(registry.trigger("agent:start", AgentStartEvent()))  # must not raise
    assert called == ["good"]
