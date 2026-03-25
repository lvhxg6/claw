"""SmartClaw Memory module — conversation persistence and auto-summarization.

Provides:
- ``MemoryStore`` — async SQLite-backed conversation history storage.
- ``AutoSummarizer`` — LLM-driven automatic conversation summarization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartclaw.memory.store import MemoryStore as MemoryStore
    from smartclaw.memory.summarizer import AutoSummarizer as AutoSummarizer


def __getattr__(name: str) -> object:
    if name == "MemoryStore":
        from smartclaw.memory.store import MemoryStore

        return MemoryStore
    if name == "AutoSummarizer":
        from smartclaw.memory.summarizer import AutoSummarizer

        return AutoSummarizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["MemoryStore", "AutoSummarizer"]
