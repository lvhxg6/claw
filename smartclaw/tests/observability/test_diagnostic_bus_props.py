# Feature: smartclaw-p2a-production-services, Property 14: 诊断事件总线分发到所有订阅者
# Feature: smartclaw-p2a-production-services, Property 15: 诊断事件总线 on/off 往返
# Feature: smartclaw-p2a-production-services, Property 16: 诊断事件总线错误隔离
# Feature: smartclaw-p2a-production-services, Property 19: 诊断事件总线独立于 OTEL
"""Property-based tests for the Diagnostic Event Bus.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 14: For any event_type and N subscribers, after emit all N receive the event.
Property 15: After on(), subscriber receives events; after off(), it no longer does.
Property 16: When some subscribers raise, remaining subscribers still receive events,
             and emit does not raise.
Property 19: Without OTEL subscribers, emit completes normally and other subscribers
             still receive events.

**Validates: Requirements 13.1, 13.2, 13.3, 13.5, 16.5, 19.5**
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import smartclaw.observability.diagnostic_bus as bus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_event_type_st = st.text(min_size=1, max_size=32, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="._"))


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Property 14: 诊断事件总线分发到所有订阅者
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 14: 诊断事件总线分发到所有订阅者
@given(
    event_type=_event_type_st,
    n=st.integers(min_value=1, max_value=10),
    payload=st.fixed_dictionaries({}),
)
@settings(max_examples=100, deadline=None)
def test_emit_dispatches_to_all_subscribers(event_type: str, n: int, payload: dict) -> None:
    """After emit, all N registered subscribers receive the event.

    **Validates: Requirements 13.1**
    """
    bus.clear()
    received: list[tuple[str, dict]] = []

    for _ in range(n):
        async def subscriber(et: str, pl: dict, _recv: list = received) -> None:
            _recv.append((et, pl))

        bus.on(event_type, subscriber)

    _run(bus.emit(event_type, payload))

    assert len(received) == n
    for et, pl in received:
        assert et == event_type
        assert pl is payload

    bus.clear()


# ---------------------------------------------------------------------------
# Property 15: 诊断事件总线 on/off 往返
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 15: 诊断事件总线 on/off 往返
@given(event_type=_event_type_st)
@settings(max_examples=100, deadline=None)
def test_on_then_emit_calls_subscriber(event_type: str) -> None:
    """After on(), subscriber receives emitted events.

    **Validates: Requirements 13.2**
    """
    bus.clear()
    received: list[str] = []

    async def subscriber(et: str, pl: dict) -> None:
        received.append(et)

    bus.on(event_type, subscriber)
    _run(bus.emit(event_type, {}))

    assert len(received) == 1
    assert received[0] == event_type
    bus.clear()


# Feature: smartclaw-p2a-production-services, Property 15: 诊断事件总线 on/off 往返
@given(event_type=_event_type_st)
@settings(max_examples=100, deadline=None)
def test_off_then_emit_does_not_call_subscriber(event_type: str) -> None:
    """After off(), subscriber no longer receives emitted events.

    **Validates: Requirements 13.3**
    """
    bus.clear()
    received: list[str] = []

    async def subscriber(et: str, pl: dict) -> None:
        received.append(et)

    bus.on(event_type, subscriber)
    bus.off(event_type, subscriber)
    _run(bus.emit(event_type, {}))

    assert len(received) == 0
    bus.clear()


# ---------------------------------------------------------------------------
# Property 16: 诊断事件总线错误隔离
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 16: 诊断事件总线错误隔离
@given(
    event_type=_event_type_st,
    n=st.integers(min_value=2, max_value=8),
    failing_indices=st.lists(
        st.integers(min_value=0, max_value=7), min_size=1, max_size=4, unique=True
    ),
)
@settings(max_examples=100, deadline=None)
def test_error_isolation_remaining_subscribers_still_called(
    event_type: str, n: int, failing_indices: list[int]
) -> None:
    """Subscribers that raise do not prevent other subscribers from running.
    emit itself does not raise.

    **Validates: Requirements 13.5**
    """
    bus.clear()
    actual_failing = {i for i in failing_indices if i < n}
    called: list[int] = []

    for i in range(n):
        if i in actual_failing:
            async def failing_sub(et: str, pl: dict, idx: int = i) -> None:
                raise RuntimeError(f"subscriber {idx} failed")

            bus.on(event_type, failing_sub)
        else:
            async def ok_sub(et: str, pl: dict, idx: int = i, _called: list = called) -> None:
                _called.append(idx)

            bus.on(event_type, ok_sub)

    # emit must not raise
    _run(bus.emit(event_type, {}))

    expected = [i for i in range(n) if i not in actual_failing]
    assert called == expected
    bus.clear()


# ---------------------------------------------------------------------------
# Property 19: 诊断事件总线独立于 OTEL
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 19: 诊断事件总线独立于 OTEL
@given(
    event_type=_event_type_st,
    n=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100, deadline=None)
def test_emit_works_without_otel_subscribers(event_type: str, n: int) -> None:
    """Without OTEL subscribers, emit completes normally and non-OTEL subscribers
    still receive events.

    **Validates: Requirements 16.5, 19.5**
    """
    bus.clear()
    # Register only plain (non-OTEL) subscribers
    received: list[str] = []

    for _ in range(n):
        async def plain_sub(et: str, pl: dict, _recv: list = received) -> None:
            _recv.append(et)

        bus.on(event_type, plain_sub)

    # emit must not raise even with no OTEL subscriber
    _run(bus.emit(event_type, {}))

    assert len(received) == n
    bus.clear()
