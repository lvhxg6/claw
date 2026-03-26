# Feature: smartclaw-p2a-production-services, Property 9: Hook register/unregister 往返
# Feature: smartclaw-p2a-production-services, Property 10: Hook trigger 按注册顺序执行
# Feature: smartclaw-p2a-production-services, Property 11: Hook 错误隔离
"""Property-based tests for the Hook registry.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 9:  register+trigger calls handler; unregister+trigger does not.
Property 10: N handlers on same hook_point are called in registration order.
Property 11: Handlers that raise do not prevent other handlers from running,
             and trigger itself does not raise.

**Validates: Requirements 9.1, 9.2, 9.3, 9.5, 11.7**
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import smartclaw.hooks.registry as registry
from smartclaw.hooks.events import AgentStartEvent, HookEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_HOOK_POINTS = list(registry.VALID_HOOK_POINTS)

_hook_point_st = st.sampled_from(VALID_HOOK_POINTS)


def _make_event(hook_point: str) -> HookEvent:
    """Return a minimal HookEvent for the given hook_point."""
    return AgentStartEvent(hook_point=hook_point)


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property 9: Hook register/unregister 往返
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 9: Hook register/unregister 往返
@given(hook_point=_hook_point_st)
@settings(max_examples=100, deadline=None)
def test_register_then_trigger_calls_handler(hook_point: str) -> None:
    """After register, trigger calls the handler.

    **Validates: Requirements 9.1, 9.2**
    """
    registry.clear()
    called: list[HookEvent] = []

    async def handler(event: HookEvent) -> None:
        called.append(event)

    registry.register(hook_point, handler)
    event = _make_event(hook_point)
    _run(registry.trigger(hook_point, event))

    assert len(called) == 1
    assert called[0] is event
    registry.clear()


# Feature: smartclaw-p2a-production-services, Property 9: Hook register/unregister 往返
@given(hook_point=_hook_point_st)
@settings(max_examples=100, deadline=None)
def test_unregister_then_trigger_does_not_call_handler(hook_point: str) -> None:
    """After unregister, trigger no longer calls the handler.

    **Validates: Requirements 9.1, 9.2**
    """
    registry.clear()
    called: list[HookEvent] = []

    async def handler(event: HookEvent) -> None:
        called.append(event)

    registry.register(hook_point, handler)
    registry.unregister(hook_point, handler)
    event = _make_event(hook_point)
    _run(registry.trigger(hook_point, event))

    assert len(called) == 0
    registry.clear()


# ---------------------------------------------------------------------------
# Property 10: Hook trigger 按注册顺序执行
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 10: Hook trigger 按注册顺序执行
@given(
    hook_point=_hook_point_st,
    n=st.integers(min_value=2, max_value=10),
)
@settings(max_examples=100, deadline=None)
def test_trigger_calls_handlers_in_registration_order(hook_point: str, n: int) -> None:
    """N handlers on the same hook_point are called in registration order.

    **Validates: Requirements 9.3**
    """
    registry.clear()
    call_order: list[int] = []

    handlers = []
    for i in range(n):
        # Capture i by default argument
        async def make_handler(event: HookEvent, idx: int = i) -> None:
            call_order.append(idx)

        handlers.append(make_handler)
        registry.register(hook_point, make_handler)

    event = _make_event(hook_point)
    _run(registry.trigger(hook_point, event))

    assert call_order == list(range(n))
    registry.clear()


# ---------------------------------------------------------------------------
# Property 11: Hook 错误隔离
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 11: Hook 错误隔离
@given(
    hook_point=_hook_point_st,
    n=st.integers(min_value=2, max_value=8),
    failing_indices=st.lists(
        st.integers(min_value=0, max_value=7), min_size=1, max_size=4, unique=True
    ),
)
@settings(max_examples=100, deadline=None)
def test_error_isolation_remaining_handlers_still_called(
    hook_point: str, n: int, failing_indices: list[int]
) -> None:
    """Handlers that raise do not prevent other handlers from running.
    trigger itself does not raise.

    **Validates: Requirements 9.5, 11.7**
    """
    registry.clear()
    # Clamp failing_indices to valid range for this n
    actual_failing = {i for i in failing_indices if i < n}
    called: list[int] = []

    for i in range(n):
        if i in actual_failing:

            async def failing_handler(event: HookEvent, idx: int = i) -> None:
                raise RuntimeError(f"handler {idx} failed")

            registry.register(hook_point, failing_handler)
        else:

            async def ok_handler(event: HookEvent, idx: int = i) -> None:
                called.append(idx)

            registry.register(hook_point, ok_handler)

    event = _make_event(hook_point)
    # trigger must not raise
    _run(registry.trigger(hook_point, event))

    # All non-failing handlers must have been called
    expected = [i for i in range(n) if i not in actual_failing]
    assert called == expected
    registry.clear()
