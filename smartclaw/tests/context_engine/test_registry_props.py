"""Property-based tests for ContextEngineRegistry (Property 24).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import BaseMessage

from smartclaw.context_engine.interface import ContextEngine
from smartclaw.context_engine.registry import ContextEngineRegistry


# ---------------------------------------------------------------------------
# Helpers: concrete ContextEngine subclass for testing
# ---------------------------------------------------------------------------


class _StubContextEngine(ContextEngine):
    """Minimal concrete ContextEngine for registry tests."""

    async def bootstrap(self, session_key: str, system_prompt: str | None = None) -> None:
        pass

    async def ingest(self, message: BaseMessage) -> None:
        pass

    async def assemble(self, messages: list[BaseMessage], system_prompt: str | None = None) -> list[BaseMessage]:
        return messages

    async def after_turn(self, session_key: str, messages: list[BaseMessage]) -> list[BaseMessage]:
        return messages

    async def compact(self, session_key: str, messages: list[BaseMessage], force: bool = False) -> list[BaseMessage]:
        return messages

    async def maintain(self) -> None:
        pass

    async def dispose(self) -> None:
        pass

    async def prepare_subagent_spawn(self, task: str, parent_context: dict[str, Any]) -> dict[str, Any]:
        return parent_context

    async def on_subagent_ended(self, task: str, result: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_engine_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() == s and len(s) > 0 and s != "legacy")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    """Save and restore registry state around each test."""
    saved = dict(ContextEngineRegistry._engines)
    yield
    ContextEngineRegistry._engines.clear()
    ContextEngineRegistry._engines.update(saved)


# ---------------------------------------------------------------------------
# Property 24: ContextEngineRegistry 注册往返
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 24: ContextEngineRegistry 注册往返
class TestContextEngineRegistryRoundTrip:
    """**Validates: Requirements 7.4**

    For any ContextEngine subclass registered with a name via
    ContextEngineRegistry.register, calling ContextEngineRegistry.get(name)
    should return the same class.
    """

    @given(name=_engine_names)
    @settings(max_examples=100)
    def test_registered_engine_is_retrievable(self, name: str) -> None:
        """After register(name, cls), get(name) returns the same class."""
        ContextEngineRegistry.register(name, _StubContextEngine)
        retrieved = ContextEngineRegistry.get(name)
        assert retrieved is _StubContextEngine

    def test_legacy_auto_registered(self) -> None:
        """LegacyContextEngine is auto-registered as 'legacy'."""
        from smartclaw.context_engine.legacy import LegacyContextEngine

        cls = ContextEngineRegistry.get("legacy")
        assert cls is LegacyContextEngine

    def test_get_unknown_raises_key_error(self) -> None:
        """get() raises KeyError for unregistered names."""
        with pytest.raises(KeyError):
            ContextEngineRegistry.get("nonexistent_engine_xyz")

    def test_register_non_subclass_raises_type_error(self) -> None:
        """register() raises TypeError for non-ContextEngine classes."""
        with pytest.raises(TypeError):
            ContextEngineRegistry.register("bad", str)  # type: ignore[arg-type]
