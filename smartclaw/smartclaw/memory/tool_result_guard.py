"""L1 ToolResultGuard — tool result truncation at write time.

Provides:

- ``ToolResultGuardConfig`` — configuration dataclass for truncation limits.
- ``ToolResultGuard`` — caps tool result content using head+tail strategy.

Reference: OpenClaw's ``capToolResultSize`` / ``truncateToolResultText``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolResultGuardConfig:
    """Configuration for L1 tool result truncation.

    Attributes:
        tool_result_max_chars: Maximum allowed characters before truncation.
        head_chars: Number of characters to keep from the start.
        tail_chars: Number of characters to keep from the end.
        tool_overrides: Per-tool override limits.
            Example: ``{"web_fetch": {"max_chars": 50000, "head_chars": 20000, "tail_chars": 10000}}``
    """

    tool_result_max_chars: int = 30000
    head_chars: int = 12000
    tail_chars: int = 8000
    tool_overrides: dict[str, dict[str, int]] = field(default_factory=dict)


class ToolResultGuard:
    """Caps tool result content using a head+tail truncation strategy.

    When content exceeds the configured ``tool_result_max_chars``, the guard
    keeps the first ``head_chars`` and last ``tail_chars`` characters, inserting
    a truncation marker in between.
    """

    def __init__(self, config: ToolResultGuardConfig | None = None) -> None:
        self._config = config or ToolResultGuardConfig()

    def cap_tool_result(self, content: str, tool_name: str = "") -> str:
        """Cap tool result content, truncating if it exceeds the limit.

        Args:
            content: The raw tool result string.
            tool_name: Optional tool name for per-tool override lookup.

        Returns:
            The original content if within limits, or a truncated version
            with head + suffix + tail.
        """
        max_chars, head_chars, tail_chars = self._get_limits(tool_name)

        if len(content) <= max_chars:
            return content

        original_length = len(content)
        head = content[:head_chars]
        tail = content[-tail_chars:] if tail_chars > 0 else ""
        suffix = (
            f"\n\n[... truncated {original_length} chars, "
            f"showing first {head_chars} + last {tail_chars} ...]\n\n"
        )
        return head + suffix + tail

    def _get_limits(self, tool_name: str) -> tuple[int, int, int]:
        """Return (max_chars, head_chars, tail_chars) for the given tool.

        If ``tool_name`` has an entry in ``tool_overrides``, those values are
        used (falling back to global defaults for any missing key).  Otherwise
        the global defaults are returned.
        """
        cfg = self._config
        overrides = cfg.tool_overrides.get(tool_name) if tool_name else None

        if overrides is not None:
            return (
                overrides.get("max_chars", cfg.tool_result_max_chars),
                overrides.get("head_chars", cfg.head_chars),
                overrides.get("tail_chars", cfg.tail_chars),
            )

        return cfg.tool_result_max_chars, cfg.head_chars, cfg.tail_chars
