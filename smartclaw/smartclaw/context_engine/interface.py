"""ContextEngine abstract interface — defines the context lifecycle.

All context management operations (bootstrap, ingest, assemble, after_turn,
compact, maintain, dispose) and Sub-Agent lifecycle hooks are declared here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import BaseMessage


class ContextEngine(ABC):
    """Abstract interface for context lifecycle management.

    Implementations control how conversation context is built, compressed,
    and maintained across turns and sub-agent spawns.
    """

    @abstractmethod
    async def bootstrap(
        self, session_key: str, system_prompt: str | None = None
    ) -> None:
        """Initialize the engine for a session.

        Args:
            session_key: Session identifier.
            system_prompt: Optional system prompt to seed context.
        """

    @abstractmethod
    async def ingest(self, message: BaseMessage) -> None:
        """Receive a new message into the engine.

        Args:
            message: The incoming message to process.
        """

    @abstractmethod
    async def assemble(
        self,
        messages: list[BaseMessage],
        system_prompt: str | None = None,
    ) -> list[BaseMessage]:
        """Assemble the LLM call context from current messages.

        Args:
            messages: Current conversation messages.
            system_prompt: Optional system prompt.

        Returns:
            Assembled message list ready for LLM invocation.
        """

    @abstractmethod
    async def after_turn(
        self, session_key: str, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        """Post-turn processing (e.g. summarization check).

        Args:
            session_key: Session identifier.
            messages: Messages after the current turn.

        Returns:
            Possibly modified message list.
        """

    @abstractmethod
    async def compact(
        self,
        session_key: str,
        messages: list[BaseMessage],
        force: bool = False,
    ) -> list[BaseMessage]:
        """Execute context compaction.

        Args:
            session_key: Session identifier.
            messages: Current messages to compact.
            force: When True, force immediate compaction.

        Returns:
            Compacted message list.
        """

    @abstractmethod
    async def maintain(self) -> None:
        """Background maintenance (e.g. cleanup, index refresh)."""

    @abstractmethod
    async def dispose(self) -> None:
        """Release all resources held by the engine."""

    # ------------------------------------------------------------------
    # Sub-Agent lifecycle hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def prepare_subagent_spawn(
        self, task: str, parent_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepare context before spawning a sub-agent.

        Args:
            task: The sub-agent task description.
            parent_context: Parent agent context to share.

        Returns:
            Context dict for the sub-agent.
        """

    @abstractmethod
    async def on_subagent_ended(self, task: str, result: str) -> None:
        """Handle sub-agent completion.

        Args:
            task: The sub-agent task description.
            result: The sub-agent's result string.
        """
