"""ContextEngineRegistry — registration and discovery of ContextEngine implementations.

Provides a class-level registry mapping engine names to their classes,
with ``register``, ``get``, and ``create`` classmethods.

The ``LegacyContextEngine`` is auto-registered as ``"legacy"`` on import.
"""

from __future__ import annotations

from typing import Any, ClassVar

from smartclaw.context_engine.interface import ContextEngine


class ContextEngineRegistry:
    """Registry for ContextEngine implementations."""

    _engines: ClassVar[dict[str, type[ContextEngine]]] = {}

    @classmethod
    def register(cls, name: str, engine_cls: type[ContextEngine]) -> None:
        """Register a ContextEngine class under *name*.

        Args:
            name: Lookup key (e.g. ``"legacy"``).
            engine_cls: A concrete subclass of ``ContextEngine``.

        Raises:
            TypeError: If *engine_cls* is not a subclass of ContextEngine.
        """
        if not (isinstance(engine_cls, type) and issubclass(engine_cls, ContextEngine)):
            raise TypeError(
                f"engine_cls must be a subclass of ContextEngine, got {engine_cls!r}"
            )
        cls._engines[name] = engine_cls

    @classmethod
    def get(cls, name: str) -> type[ContextEngine]:
        """Return the ContextEngine class registered under *name*.

        Raises:
            KeyError: If no engine is registered with that name.
        """
        if name not in cls._engines:
            raise KeyError(
                f"No ContextEngine registered with name '{name}'. "
                f"Available: {sorted(cls._engines)}"
            )
        return cls._engines[name]

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> ContextEngine:
        """Instantiate the ContextEngine registered under *name*.

        Args:
            name: Lookup key.
            **kwargs: Passed to the engine constructor.

        Returns:
            A new ContextEngine instance.

        Raises:
            KeyError: If no engine is registered with that name.
        """
        engine_cls = cls.get(name)
        return engine_cls(**kwargs)


# Auto-register LegacyContextEngine as "legacy"
def _auto_register_legacy() -> None:
    from smartclaw.context_engine.legacy import LegacyContextEngine

    ContextEngineRegistry.register("legacy", LegacyContextEngine)


_auto_register_legacy()
