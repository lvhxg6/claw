"""Hook registry — register / unregister / trigger lifecycle handlers.

Module-level singleton: all functions operate on the shared ``_registry``
dictionary.  ``clear()`` resets state (useful in tests).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from smartclaw.hooks.events import HookEvent

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

HookHandler = Callable[[HookEvent], Awaitable[None]]

# ---------------------------------------------------------------------------
# Valid hook points
# ---------------------------------------------------------------------------

VALID_HOOK_POINTS: frozenset[str] = frozenset(
    {
        "tool:before",
        "tool:after",
        "agent:start",
        "agent:end",
        "llm:before",
        "llm:after",
        "session:start",
        "session:end",
    }
)

# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

_registry: dict[str, list[HookHandler]] = {}

_log = structlog.get_logger(component="hooks.registry")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(hook_point: str, handler: HookHandler) -> None:
    """Register *handler* for *hook_point*.

    Raises ``ValueError`` if *hook_point* is not in ``VALID_HOOK_POINTS``.
    """
    if hook_point not in VALID_HOOK_POINTS:
        raise ValueError(
            f"Invalid hook_point {hook_point!r}. "
            f"Must be one of {sorted(VALID_HOOK_POINTS)}"
        )
    _registry.setdefault(hook_point, []).append(handler)


def unregister(hook_point: str, handler: HookHandler) -> None:
    """Remove a specific *handler* from *hook_point*.

    Silently does nothing if the handler is not registered.
    """
    handlers = _registry.get(hook_point)
    if handlers is None:
        return
    try:
        handlers.remove(handler)
    except ValueError:
        pass


async def trigger(hook_point: str, event: HookEvent) -> None:
    """Invoke all handlers registered for *hook_point* in order.

    Each handler is called sequentially.  If a handler raises, the
    exception is logged and execution continues with the next handler
    (error isolation).
    """
    handlers = _registry.get(hook_point)
    if not handlers:
        return
    for handler in handlers:
        try:
            await handler(event)
        except Exception:
            _log.error(
                "hook_handler_error",
                hook_point=hook_point,
                handler=getattr(handler, "__name__", repr(handler)),
                exc_info=True,
            )


def clear() -> None:
    """Remove all registered handlers (testing helper)."""
    _registry.clear()


def get_handlers(hook_point: str) -> list[HookHandler]:
    """Return the list of handlers for *hook_point* (testing helper)."""
    return list(_registry.get(hook_point, []))
