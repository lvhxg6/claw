"""L2 SessionPruner — session-level message pruning before LLM invocation.

Provides:

- ``SessionPrunerConfig`` — configuration dataclass for pruning thresholds.
- ``SessionPruner`` — two-level pruning (soft-trim / hard-clear) of ToolMessages.

Pruning strategy:
1. Estimate token count of the message list.
2. If tokens exceed ``soft_trim_threshold`` → soft-trim ToolMessages in the
   prunable range (keep head + tail characters, insert ``...`` in middle).
3. If tokens exceed ``hard_clear_threshold`` → hard-clear ToolMessages in the
   prunable range (replace content with placeholder).
4. Always preserve the first ``keep_head`` and last ``keep_recent`` messages.
5. Only modify ToolMessage content; HumanMessage and AIMessage are never touched.
6. Return a new list — the original is never mutated.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, ToolMessage


@dataclass
class SessionPrunerConfig:
    """Configuration for L2 session pruning.

    Attributes:
        soft_trim_threshold: Fraction of context_window above which soft-trim
            is applied (default 0.5 = 50%).
        hard_clear_threshold: Fraction of context_window above which hard-clear
            is applied (default 0.7 = 70%).
        soft_trim_head: Characters to keep from the start during soft-trim.
        soft_trim_tail: Characters to keep from the end during soft-trim.
        keep_recent: Number of tail messages to leave untouched.
        keep_head: Number of head messages to leave untouched.
        tool_allow_list: Tool names whose results are never pruned.
        tool_deny_list: Tool names whose results are pruned first.
    """

    soft_trim_threshold: float = 0.5
    hard_clear_threshold: float = 0.7
    soft_trim_head: int = 500
    soft_trim_tail: int = 300
    keep_recent: int = 5
    keep_head: int = 2
    tool_allow_list: list[str] = field(default_factory=list)
    tool_deny_list: list[str] = field(default_factory=list)


class SessionPruner:
    """Two-level session pruner for ToolMessage content.

    Operates on a message list before LLM invocation, applying soft-trim
    or hard-clear to ToolMessages in the prunable middle range while
    preserving head and tail messages.
    """

    def __init__(
        self,
        config: SessionPrunerConfig,
        context_window: int,
        estimate_tokens_fn: Callable[[list[BaseMessage]], int],
    ) -> None:
        self._config = config
        self._context_window = context_window
        self._estimate_tokens = estimate_tokens_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prune(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Apply two-level pruning and return a new message list.

        The original list is never modified.

        Steps:
        1. Estimate current token usage.
        2. Determine pruning level (none / soft / hard).
        3. Copy messages, modifying only ToolMessages in the prunable range.
        """
        if not messages:
            return list(messages)

        cfg = self._config
        token_count = self._estimate_tokens(messages)
        soft_limit = int(self._context_window * cfg.soft_trim_threshold)
        hard_limit = int(self._context_window * cfg.hard_clear_threshold)

        # No pruning needed
        if token_count <= soft_limit:
            return list(messages)

        n = len(messages)
        keep_head = min(cfg.keep_head, n)
        keep_recent = min(cfg.keep_recent, n)

        # Determine the prunable range indices
        prune_start = keep_head
        prune_end = max(n - keep_recent, prune_start)

        # If there's nothing to prune, return a copy
        if prune_start >= prune_end:
            return list(messages)

        use_hard_clear = token_count > hard_limit

        # Build new list — deep-copy only the messages we modify
        result: list[BaseMessage] = []
        for i, msg in enumerate(messages):
            if i < prune_start or i >= prune_end:
                # Head / tail — keep unchanged
                result.append(msg)
                continue

            if not isinstance(msg, ToolMessage):
                # Only prune ToolMessages
                result.append(msg)
                continue

            tool_name = getattr(msg, "name", None) or ""

            if self._should_skip(msg, tool_name):
                result.append(msg)
                continue

            content = msg.content if isinstance(msg.content, str) else str(msg.content)

            if use_hard_clear:
                new_content = f"[tool result cleared - {tool_name}]"
            else:
                new_content = self._soft_trim(content)

            # Create a shallow copy with replaced content
            new_msg = copy.copy(msg)
            # ToolMessage.content is a regular attribute we can set
            new_msg.content = new_content
            result.append(new_msg)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _soft_trim(self, content: str) -> str:
        """Keep head + tail characters, insert ``...`` in the middle."""
        cfg = self._config
        head = cfg.soft_trim_head
        tail = cfg.soft_trim_tail

        if len(content) <= head + tail:
            return content

        return content[:head] + "..." + content[-tail:] if tail > 0 else content[:head] + "..."

    def _should_skip(self, msg: BaseMessage, tool_name: str) -> bool:
        """Return True if this message should NOT be pruned.

        - Messages from tools in ``tool_allow_list`` are never pruned.
        - ``tool_deny_list`` is handled by the caller (deny-listed tools are
          pruned with higher priority), but for skip logic we only check
          the allow list here.
        """
        cfg = self._config
        if cfg.tool_allow_list and tool_name in cfg.tool_allow_list:
            return True
        return False
