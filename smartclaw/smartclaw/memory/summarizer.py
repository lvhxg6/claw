"""AutoSummarizer — LLM-driven automatic conversation summarization.

Monitors conversation length and triggers LLM-based summarization when
thresholds are exceeded. Adapted from PicoClaw's ``maybeSummarize``,
``summarizeSession``, and ``forceCompression`` logic.

Enhanced with L3 pre-compaction memory flush and L4 multi-stage compaction.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
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

# Hardcoded fallback text used when all compression attempts fail
_HARDCODED_FALLBACK = (
    "[Previous conversation history was compressed due to context limits. "
    "Key context may have been lost. Please re-state important details if needed.]"
)


class AutoSummarizer:
    """LLM-driven automatic conversation summarization and compression.

    Supports L3 pre-compaction memory flush and L4 multi-stage compaction
    in addition to the original simple summarization.
    """

    def __init__(
        self,
        store: MemoryStore,
        model_config: ModelConfig,
        *,
        message_threshold: int = 20,
        token_percent_threshold: int = 70,
        context_window: int = 128_000,
        keep_recent: int = 5,
        compaction_model: str | None = None,
        identifier_policy: str = "strict",
        identifier_patterns: list[str] | None = None,
        chunk_max_tokens: int = 4000,
        part_max_tokens: int = 2000,
    ) -> None:
        self._store = store
        self._model_config = model_config
        self._message_threshold = message_threshold
        self._token_percent_threshold = token_percent_threshold
        self._context_window = context_window
        self._keep_recent = keep_recent
        # L3/L4 config
        self._compaction_model = compaction_model
        self._identifier_policy = identifier_policy
        self._identifier_patterns = identifier_patterns or []
        self._chunk_max_tokens = chunk_max_tokens
        self._part_max_tokens = part_max_tokens

    # ------------------------------------------------------------------
    # L3/L4 config helpers
    # ------------------------------------------------------------------

    def _get_compaction_model_config(self) -> ModelConfig:
        """Return a ModelConfig for the compaction-dedicated LLM.

        If ``compaction_model`` is set, returns a ModelConfig with that model
        as primary (keeping the same fallbacks). Otherwise returns the
        original ``_model_config``.
        """
        if self._compaction_model:
            return ModelConfig(
                primary=self._compaction_model,
                fallbacks=list(self._model_config.fallbacks),
                temperature=self._model_config.temperature,
                max_tokens=self._model_config.max_tokens,
            )
        return self._model_config

    def _build_identifier_instructions(self) -> str:
        """Build identifier preservation instructions based on policy.

        Returns:
            Non-empty instructions for "strict" and "custom", empty string for "off".
        """
        if self._identifier_policy == "strict":
            return (
                "IMPORTANT: You MUST preserve ALL identifiers in the summary, including:\n"
                "- File paths (e.g. src/main.py, config/settings.yaml)\n"
                "- Variable names and function names\n"
                "- Class names and module names\n"
                "- API endpoints and URLs\n"
                "- Configuration keys and environment variable names\n"
                "Do NOT omit or abbreviate any identifier."
            )
        if self._identifier_policy == "custom" and self._identifier_patterns:
            patterns = ", ".join(self._identifier_patterns)
            return (
                f"IMPORTANT: You MUST preserve identifiers matching these patterns "
                f"in the summary: {patterns}\n"
                "Do NOT omit or abbreviate these identifiers."
            )
        # "off" or "custom" with no patterns
        return ""

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
    # L3: Pre-compaction memory flush
    # ------------------------------------------------------------------

    async def _memory_flush(
        self,
        session_key: str,
        messages: list[BaseMessage],
    ) -> None:
        """L3: Extract key identifiers, decision points, and pending tasks.

        Sends a specialized prompt to the LLM to extract structured context
        from the current conversation, then merges the result with the
        existing summary using ``\\n\\n---\\n\\n`` as separator.

        On failure: logs a warning and returns without interrupting L4.
        """
        if not messages:
            return

        identifier_instructions = self._build_identifier_instructions()
        prompt_parts: list[str] = [
            "Analyze the following conversation and extract a structured summary containing:\n"
            "1. KEY IDENTIFIERS: All file paths, variable names, function names, class names, "
            "API endpoints, and configuration keys mentioned.\n"
            "2. DECISION POINTS: Important decisions made during the conversation.\n"
            "3. PENDING TASKS: Any unfinished tasks or next steps mentioned.\n"
            "\nProvide a concise, structured output.",
        ]
        if identifier_instructions:
            prompt_parts.append(f"\n{identifier_instructions}")

        prompt_parts.append("\nCONVERSATION:")
        for msg in messages:
            role = msg.type
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Truncate very long messages in the prompt to avoid blowing up
            if len(content) > 2000:
                content = content[:1000] + "..." + content[-500:]
            prompt_parts.append(f"{role}: {content}")

        prompt = "\n".join(prompt_parts)

        try:
            compaction_config = self._get_compaction_model_config()
            flush_text = await self._call_llm_summarize_with_config(
                prompt, compaction_config
            )
            if flush_text:
                existing_summary = await self._store.get_summary(session_key)
                if existing_summary:
                    merged = existing_summary + "\n\n---\n\n" + flush_text
                else:
                    merged = flush_text
                await self._store.set_summary(session_key, merged)
                logger.info(
                    "memory_flush_complete",
                    session_key=session_key,
                    flush_length=len(flush_text),
                )
        except Exception as exc:
            logger.warning(
                "memory_flush_failed",
                session_key=session_key,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # L4: Multi-stage compaction
    # ------------------------------------------------------------------

    def _chunk_messages(
        self,
        messages: list[BaseMessage],
        chunk_max_tokens: int | None = None,
    ) -> list[list[BaseMessage]]:
        """Split messages into chunks at HumanMessage turn boundaries.

        Each chunk's estimated token count stays within *chunk_max_tokens*.
        Chunks always start at a HumanMessage boundary to avoid splitting
        tool-call sequences.
        """
        max_tokens = chunk_max_tokens or self._chunk_max_tokens
        if not messages:
            return []

        chunks: list[list[BaseMessage]] = []
        current_chunk: list[BaseMessage] = []
        current_tokens = 0

        for msg in messages:
            msg_tokens = self.estimate_tokens([msg])

            # If adding this message would exceed the limit AND we have
            # content AND this is a HumanMessage (turn boundary), start new chunk
            if (
                current_chunk
                and current_tokens + msg_tokens > max_tokens
                and isinstance(msg, HumanMessage)
            ):
                chunks.append(current_chunk)
                current_chunk = [msg]
                current_tokens = msg_tokens
            else:
                current_chunk.append(msg)
                current_tokens += msg_tokens

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def _multi_stage_compact(
        self,
        session_key: str,
        messages: list[BaseMessage],
        existing_summary: str,
        chunk_max_tokens: int | None = None,
    ) -> str | None:
        """L4: Multi-stage chunked compaction.

        1. Chunk messages by chunk_max_tokens at turn boundaries.
        2. Sequentially summarize each chunk (with prior summaries as context).
        3. Split chunks exceeding part_max_tokens into sub-chunks.
        4. Include identifier preservation instructions.

        Returns the final merged summary text, or None on total failure.
        """
        compaction_config = self._get_compaction_model_config()
        identifier_instructions = self._build_identifier_instructions()

        chunks = self._chunk_messages(messages, chunk_max_tokens)
        if not chunks:
            return None

        running_summary = existing_summary or ""

        for i, chunk in enumerate(chunks):
            chunk_summary = await self._summarize_chunk(
                chunk, running_summary, identifier_instructions, compaction_config
            )
            if chunk_summary is None:
                # Skip failed chunk, keep running summary as-is
                logger.warning(
                    "chunk_summarization_failed",
                    session_key=session_key,
                    chunk_index=i,
                )
                continue

            # Check if chunk summary exceeds part_max_tokens
            summary_tokens = self.estimate_tokens(
                [HumanMessage(content=chunk_summary)]
            )
            if summary_tokens > self._part_max_tokens:
                # Split into sub-chunks and re-summarize
                sub_summary = await self._summarize_oversized_chunk(
                    chunk_summary, identifier_instructions, compaction_config
                )
                if sub_summary:
                    chunk_summary = sub_summary

            running_summary = chunk_summary

        return running_summary if running_summary else None

    async def _summarize_chunk(
        self,
        chunk: list[BaseMessage],
        prior_summary: str,
        identifier_instructions: str,
        config: ModelConfig,
    ) -> str | None:
        """Summarize a single chunk with prior context."""
        parts: list[str] = [
            "Provide a concise summary of this conversation segment, "
            "preserving core context, key decisions, and important details.",
        ]
        if identifier_instructions:
            parts.append(identifier_instructions)
        if prior_summary:
            parts.append(f"\nPrior context summary:\n{prior_summary}")

        parts.append("\nCONVERSATION SEGMENT:")
        for msg in chunk:
            role = msg.type
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 3000:
                content = content[:1500] + "..." + content[-500:]
            parts.append(f"{role}: {content}")

        prompt = "\n".join(parts)
        return await self._call_llm_summarize_with_config(prompt, config)

    async def _summarize_oversized_chunk(
        self,
        chunk_summary: str,
        identifier_instructions: str,
        config: ModelConfig,
    ) -> str | None:
        """Re-summarize an oversized chunk summary by splitting into parts."""
        # Split the text roughly in half
        mid = len(chunk_summary) // 2
        part1 = chunk_summary[:mid]
        part2 = chunk_summary[mid:]

        parts_summaries: list[str] = []
        for part in [part1, part2]:
            prompt_parts = [
                "Condense the following text into a shorter summary, "
                "preserving all key information.",
            ]
            if identifier_instructions:
                prompt_parts.append(identifier_instructions)
            prompt_parts.append(f"\nTEXT:\n{part}")
            prompt = "\n".join(prompt_parts)
            result = await self._call_llm_summarize_with_config(prompt, config)
            if result:
                parts_summaries.append(result)

        if parts_summaries:
            return "\n\n".join(parts_summaries)
        return None

    async def _summarize_with_fallback(
        self,
        session_key: str,
        messages: list[BaseMessage],
        existing_summary: str,
    ) -> str | None:
        """Progressive fallback strategy for L4 compaction.

        Attempt 1: Full compression via _multi_stage_compact.
        Attempt 2: Filter oversized ToolMessages (>50% of context_window), retry.
        Attempt 3: Hardcoded fallback text.
        """
        # Attempt 1: full compression
        result = await self._multi_stage_compact(
            session_key, messages, existing_summary
        )
        if result is not None:
            return result

        logger.warning(
            "full_compression_failed_trying_filtered",
            session_key=session_key,
        )

        # Attempt 2: filter oversized ToolMessages and retry
        tool_size_limit = self._context_window // 2  # 50% of context_window
        filtered: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if self.estimate_tokens([msg]) > tool_size_limit:
                    # Replace with placeholder
                    tool_name = getattr(msg, "name", "unknown")
                    filtered.append(
                        ToolMessage(
                            content=f"[large tool result removed - {tool_name}]",
                            tool_call_id=getattr(msg, "tool_call_id", ""),
                            name=tool_name,
                        )
                    )
                    continue
            filtered.append(msg)

        result = await self._multi_stage_compact(
            session_key, filtered, existing_summary
        )
        if result is not None:
            return result

        logger.warning(
            "filtered_compression_failed_using_hardcoded",
            session_key=session_key,
        )

        # Attempt 3: hardcoded fallback
        return _HARDCODED_FALLBACK

    async def _overflow_recovery(
        self,
        session_key: str,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Overflow recovery: retry compaction with halved chunk_max_tokens.

        Retries up to 3 times with exponential backoff (1s, 2s, 4s).
        Each retry halves chunk_max_tokens for more aggressive chunking.
        """
        current_chunk_max = self._chunk_max_tokens
        existing_summary = await self._store.get_summary(session_key)

        for attempt in range(3):
            current_chunk_max = max(current_chunk_max // 2, 100)
            backoff = 2 ** attempt  # 1, 2, 4
            await asyncio.sleep(backoff)

            logger.info(
                "overflow_recovery_attempt",
                session_key=session_key,
                attempt=attempt + 1,
                chunk_max_tokens=current_chunk_max,
            )

            result = await self._multi_stage_compact(
                session_key, messages, existing_summary,
                chunk_max_tokens=current_chunk_max,
            )
            if result is not None:
                await self._store.set_summary(session_key, result)
                await self._store.truncate_history(
                    session_key, self._keep_recent
                )
                return messages[-self._keep_recent:] if len(messages) > self._keep_recent else messages

        # All retries failed — use force_compression as last resort
        return await self.force_compression(session_key, messages)

    # ------------------------------------------------------------------
    # LLM call with specific config
    # ------------------------------------------------------------------

    async def _call_llm_summarize_with_config(
        self, prompt: str, config: ModelConfig
    ) -> str | None:
        """Call the LLM via FallbackChain using a specific ModelConfig.

        Returns the summary text, or None on failure.
        """
        primary_provider, primary_model = parse_model_ref(config.primary)
        candidates = [
            FallbackCandidate(provider=primary_provider, model=primary_model)
        ]
        for ref in config.fallbacks:
            p, m = parse_model_ref(ref)
            candidates.append(FallbackCandidate(provider=p, model=m))

        fallback_chain = FallbackChain()

        async def run(provider: str, model: str) -> AIMessage:
            llm = ProviderFactory.create(
                provider,
                model,
                temperature=0.3,
                max_tokens=config.max_tokens,
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
    # maybe_summarize (enhanced with L3 + L4)
    # ------------------------------------------------------------------

    async def maybe_summarize(
        self,
        session_key: str,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """Check dual thresholds and trigger L3 + L4 summarization if exceeded.

        Thresholds:
        - Message count > message_threshold
        - Estimated tokens > token_percent_threshold% of context_window

        Pipeline:
        1. Check thresholds
        2. L3: Pre-compaction memory flush
        3. L4: Multi-stage compaction via _summarize_with_fallback
        4. Persist and truncate

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

        # L3: Pre-compaction memory flush (failure does not block L4)
        try:
            await self._memory_flush(session_key, to_summarize)
        except Exception as flush_exc:
            logger.warning(
                "memory_flush_exception_in_maybe_summarize",
                session_key=session_key,
                error=str(flush_exc),
            )

        # L4: Multi-stage compaction with progressive fallback
        existing_summary = await self._store.get_summary(session_key)
        summary_text = await self._summarize_with_fallback(
            session_key, to_summarize, existing_summary
        )
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
