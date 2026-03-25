"""AutoSummarizer — LLM-driven automatic conversation summarization.

Monitors conversation length and triggers LLM-based summarization when
thresholds are exceeded. Adapted from PicoClaw's ``maybeSummarize``,
``summarizeSession``, and ``forceCompression`` logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from smartclaw.providers.config import ModelConfig, parse_model_ref
from smartclaw.providers.factory import ProviderFactory
from smartclaw.providers.fallback import (
    FallbackCandidate,
    FallbackChain,
)

if TYPE_CHECKING:
    from smartclaw.memory.store import MemoryStore

logger = structlog.get_logger(component="memory.summarizer")


class AutoSummarizer:
    """LLM-driven automatic conversation summarization and compression."""

    def __init__(
        self,
        store: MemoryStore,
        model_config: ModelConfig,
        *,
        message_threshold: int = 20,
        token_percent_threshold: int = 70,
        context_window: int = 128_000,
        keep_recent: int = 5,
    ) -> None:
        self._store = store
        self._model_config = model_config
        self._message_threshold = message_threshold
        self._token_percent_threshold = token_percent_threshold
        self._context_window = context_window
        self._keep_recent = keep_recent

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, messages: list[BaseMessage]) -> int:
        """Heuristic token estimation (~2.5 chars per token).

        Counts content length, tool_calls arguments, tool_call_id,
        and a per-message overhead of 12 characters. Mirrors PicoClaw's
        ``estimateMessageTokens`` logic.

        Formula: total_chars * 2 / 5
        """
        total_chars = 0
        for msg in messages:
            # Content
            content = msg.content
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Multimodal content blocks
                for block in content:
                    if isinstance(block, dict):
                        total_chars += len(block.get("text", ""))
                    elif isinstance(block, str):
                        total_chars += len(block)

            # AIMessage tool_calls
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    total_chars += len(tc.get("name", ""))
                    args = tc.get("args", {})
                    if isinstance(args, str):
                        total_chars += len(args)
                    elif isinstance(args, dict):
                        total_chars += len(str(args))

            # ToolMessage tool_call_id
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                total_chars += len(tool_call_id)

            # Per-message overhead (role label, JSON structure, separators)
            total_chars += 12

        return total_chars * 2 // 5

    # ------------------------------------------------------------------
    # Turn boundary detection
    # ------------------------------------------------------------------

    @staticmethod
    def find_safe_boundary(
        messages: list[BaseMessage], target_index: int
    ) -> int:
        """Find the nearest turn boundary (HumanMessage) at or before *target_index*.

        Searches backward from *target_index* to locate a HumanMessage,
        ensuring no tool-call sequence is split. Returns 0 if no safe
        boundary is found.
        """
        if not messages or target_index <= 0:
            return 0
        idx = min(target_index, len(messages) - 1)
        while idx > 0:
            if isinstance(messages[idx], HumanMessage):
                return idx
            idx -= 1
        return 0

    # ------------------------------------------------------------------
    # LLM summarization call
    # ------------------------------------------------------------------

    async def _call_llm_summarize(
        self, prompt: str
    ) -> str | None:
        """Call the LLM via FallbackChain to generate a summary.

        Returns the summary text, or None on failure.
        """
        primary_provider, primary_model = parse_model_ref(
            self._model_config.primary
        )
        candidates = [
            FallbackCandidate(provider=primary_provider, model=primary_model)
        ]
        for ref in self._model_config.fallbacks:
            p, m = parse_model_ref(ref)
            candidates.append(FallbackCandidate(provider=p, model=m))

        fallback_chain = FallbackChain()

        async def run(provider: str, model: str) -> AIMessage:
            llm = ProviderFactory.create(
                provider,
                model,
                temperature=0.3,
                max_tokens=self._model_config.max_tokens,
            )
            result = await llm.ainvoke(
                [HumanMessage(content=prompt)]
            )
            if not isinstance(result, AIMessage):
                return AIMessage(content=str(result.content))
            return result

        try:
            fb_result = await fallback_chain.execute(candidates, run)
            content = fb_result.response.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # maybe_summarize
    # ------------------------------------------------------------------

    async def maybe_summarize(
        self,
        session_key: str,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Check dual thresholds and trigger summarization if exceeded.

        Thresholds:
        - Message count > message_threshold
        - Estimated tokens > token_percent_threshold% of context_window

        On LLM failure: logs error, returns messages unchanged.
        """
        token_estimate = self.estimate_tokens(messages)
        token_threshold = (
            self._context_window * self._token_percent_threshold // 100
        )

        if (
            len(messages) <= self._message_threshold
            and token_estimate <= token_threshold
        ):
            return messages

        logger.info(
            "summarization_triggered",
            session_key=session_key,
            message_count=len(messages),
            token_estimate=token_estimate,
            token_threshold=token_threshold,
        )

        # Find safe boundary to split: keep the most recent keep_recent
        # messages, summarize everything before the boundary.
        target = len(messages) - self._keep_recent
        if target <= 0:
            return messages

        safe_cut = self.find_safe_boundary(messages, target)
        if safe_cut <= 0:
            logger.debug(
                "no_safe_boundary_for_summarization",
                session_key=session_key,
            )
            return messages

        to_summarize = messages[:safe_cut]

        # Build summarization prompt
        existing_summary = await self._store.get_summary(session_key)
        prompt = self._build_summarize_prompt(to_summarize, existing_summary)

        summary_text = await self._call_llm_summarize(prompt)
        if summary_text is None:
            logger.error(
                "summarization_llm_failed",
                session_key=session_key,
            )
            return messages

        # Persist summary and truncate history
        await self._store.set_summary(session_key, summary_text)
        await self._store.truncate_history(
            session_key, self._keep_recent
        )

        logger.info(
            "summarization_complete",
            session_key=session_key,
            summarized_count=len(to_summarize),
            kept_count=self._keep_recent,
            summary_length=len(summary_text),
        )

        # Return the kept (recent) portion of messages
        return messages[safe_cut:]

    # ------------------------------------------------------------------
    # force_compression
    # ------------------------------------------------------------------

    async def force_compression(
        self,
        session_key: str,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Emergency compression: drop oldest ~50% of messages at turn boundary.

        - Skip if < 4 messages.
        - Find safe boundary at ~50% point, drop older messages.
        - If no safe boundary: keep only most recent user message as last resort.
        - Record compression note in summary via store.set_summary.
        - Replace history via store.set_history.
        """
        if len(messages) < 4:
            return messages

        mid = len(messages) // 2
        safe_cut = self.find_safe_boundary(messages, mid)

        if safe_cut <= 0:
            # No safe boundary — keep only the most recent user message
            kept: list[BaseMessage] = []
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    kept = [msg]
                    break
            if not kept:
                # No user message at all — return unchanged
                return messages
        else:
            kept = messages[safe_cut:]

        dropped_count = len(messages) - len(kept)

        # Record compression note in summary
        existing_summary = await self._store.get_summary(session_key)
        compression_note = (
            f"[Emergency compression dropped {dropped_count} oldest "
            f"messages due to context limit]"
        )
        if existing_summary:
            compression_note = existing_summary + "\n\n" + compression_note

        await self._store.set_summary(session_key, compression_note)
        await self._store.set_history(session_key, kept)

        logger.warning(
            "force_compression_executed",
            session_key=session_key,
            dropped_count=dropped_count,
            remaining_count=len(kept),
        )

        return kept

    # ------------------------------------------------------------------
    # build_context
    # ------------------------------------------------------------------

    async def build_context(
        self,
        session_key: str,
        messages: list[BaseMessage],
        system_prompt: str | None = None,
    ) -> list[BaseMessage]:
        """Build LLM context by prepending summary as a SystemMessage.

        If a summary exists, inserts a SystemMessage containing the summary
        text after any existing system prompt but before all non-system
        messages.
        """
        summary = await self._store.get_summary(session_key)
        if not summary:
            return messages

        summary_msg = SystemMessage(
            content=f"Previous conversation summary:\n{summary}"
        )

        # Insert summary after any leading system messages
        result: list[BaseMessage] = []
        inserted = False
        for msg in messages:
            if not inserted and not isinstance(msg, SystemMessage):
                result.append(summary_msg)
                inserted = True
            result.append(msg)

        # If all messages are SystemMessages (unlikely), append at end
        if not inserted:
            result.append(summary_msg)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summarize_prompt(
        messages: list[BaseMessage], existing_summary: str
    ) -> str:
        """Build the LLM prompt for summarization."""
        parts: list[str] = [
            "Provide a concise summary of this conversation segment, "
            "preserving core context and key points."
        ]
        if existing_summary:
            parts.append(f"Existing context: {existing_summary}")

        parts.append("\nCONVERSATION:")
        for msg in messages:
            role = msg.type  # "human", "ai", "tool", "system"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            parts.append(f"{role}: {content}")

        return "\n".join(parts)
