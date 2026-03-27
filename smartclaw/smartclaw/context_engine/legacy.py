"""LegacyContextEngine — default ContextEngine wrapping AutoSummarizer.

Delegates context lifecycle operations to the existing AutoSummarizer,
MemoryStore, and optional SessionPruner components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from langchain_core.messages import BaseMessage

from smartclaw.context_engine.interface import ContextEngine

if TYPE_CHECKING:
    from smartclaw.memory.pruning import SessionPruner
    from smartclaw.memory.store import MemoryStore
    from smartclaw.memory.summarizer import AutoSummarizer

logger = structlog.get_logger(component="context_engine.legacy")


class LegacyContextEngine(ContextEngine):
    """Default ContextEngine implementation wrapping AutoSummarizer.

    Maps the ContextEngine lifecycle to existing summarizer methods:
    - ``assemble`` → ``summarizer.build_context``
    - ``after_turn`` → ``summarizer.maybe_summarize``
    - ``compact(force=True)`` → ``summarizer.force_compression``
    - ``compact(force=False)`` → ``summarizer.maybe_summarize``
    """

    def __init__(
        self,
        summarizer: AutoSummarizer,
        store: MemoryStore,
        pruner: SessionPruner | None = None,
    ) -> None:
        self._summarizer = summarizer
        self._store = store
        self._pruner = pruner
        self._session_key: str | None = None

    async def bootstrap(
        self, session_key: str, system_prompt: str | None = None
    ) -> None:
        self._session_key = session_key
        logger.debug("legacy_engine_bootstrap", session_key=session_key)

    async def ingest(self, message: BaseMessage) -> None:
        # LegacyContextEngine does not need per-message ingestion;
        # messages are managed externally via MemoryStore.
        pass

    async def assemble(
        self,
        messages: list[BaseMessage],
        system_prompt: str | None = None,
    ) -> list[BaseMessage]:
        session_key = self._session_key or ""
        result = await self._summarizer.build_context(
            session_key, messages, system_prompt=system_prompt
        )
        if self._pruner is not None:
            result = self._pruner.prune(result)
        return result

    async def after_turn(
        self, session_key: str, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        return await self._summarizer.maybe_summarize(session_key, messages)

    async def compact(
        self,
        session_key: str,
        messages: list[BaseMessage],
        force: bool = False,
    ) -> list[BaseMessage]:
        if force:
            return await self._summarizer.force_compression(
                session_key, messages
            )
        return await self._summarizer.maybe_summarize(session_key, messages)

    async def maintain(self) -> None:
        # No background maintenance in the legacy engine.
        pass

    async def dispose(self) -> None:
        logger.debug("legacy_engine_disposed")

    # ------------------------------------------------------------------
    # Sub-Agent lifecycle hooks
    # ------------------------------------------------------------------

    async def prepare_subagent_spawn(
        self, task: str, parent_context: dict[str, Any]
    ) -> dict[str, Any]:
        # Legacy engine passes parent context through unchanged.
        logger.debug("legacy_prepare_subagent", task=task[:100])
        return dict(parent_context)

    async def on_subagent_ended(self, task: str, result: str) -> None:
        logger.debug(
            "legacy_subagent_ended",
            task=task[:100],
            result_len=len(result),
        )
