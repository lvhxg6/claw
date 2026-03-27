"""Property-based tests for ToolResultGuard (Properties 11–13).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.memory.tool_result_guard import ToolResultGuard, ToolResultGuardConfig


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Tool names
_tool_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)


def _build_suffix(original_length: int, head_chars: int, tail_chars: int) -> str:
    """Reproduce the exact truncation suffix format."""
    return (
        f"\n\n[... truncated {original_length} chars, "
        f"showing first {head_chars} + last {tail_chars} ...]\n\n"
    )


# ---------------------------------------------------------------------------
# Property 11: L1 工具结果截断 — head+tail 保留
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 11: L1 工具结果截断 — head+tail 保留
class TestToolResultTruncationHeadTail:
    """**Validates: Requirements 3.2, 3.3**

    For any string content longer than tool_result_max_chars, after
    cap_tool_result the result should:
    (a) start with the first head_chars characters of the original,
    (b) end with the last tail_chars characters of the original,
    (c) contain a truncation suffix with the original content length,
    (d) have total length ≤ head_chars + tail_chars + len(suffix).
    """

    @given(
        max_chars=st.integers(min_value=100, max_value=5000),
        head_frac=st.floats(min_value=0.1, max_value=0.3),
        tail_frac=st.floats(min_value=0.05, max_value=0.2),
        extra_len=st.integers(min_value=1, max_value=5000),
        seed_char=st.characters(whitelist_categories=("L", "N")),
    )
    @settings(max_examples=100)
    def test_truncation_preserves_head_and_tail(
        self,
        max_chars: int,
        head_frac: float,
        tail_frac: float,
        extra_len: int,
        seed_char: str,
    ) -> None:
        head_chars = max(10, int(max_chars * head_frac))
        tail_chars = max(10, int(max_chars * tail_frac))

        # Generate content that exceeds max_chars using repetition + index markers
        content_len = max_chars + extra_len
        # Build a unique content string so head/tail are distinguishable
        base = "".join(chr(ord("A") + (i % 26)) for i in range(min(content_len, 1000)))
        content = (base * ((content_len // len(base)) + 1))[:content_len]

        config = ToolResultGuardConfig(
            tool_result_max_chars=max_chars,
            head_chars=head_chars,
            tail_chars=tail_chars,
        )
        guard = ToolResultGuard(config)
        result = guard.cap_tool_result(content)

        # (a) starts with first head_chars
        assert result[:head_chars] == content[:head_chars]

        # (b) ends with last tail_chars
        if tail_chars > 0:
            assert result[-tail_chars:] == content[-tail_chars:]

        # (c) contains truncation suffix with original length
        suffix = _build_suffix(len(content), head_chars, tail_chars)
        assert suffix in result

        # (d) total length ≤ head_chars + tail_chars + len(suffix)
        assert len(result) <= head_chars + tail_chars + len(suffix)


# ---------------------------------------------------------------------------
# Property 12: L1 截断不修改短内容
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 12: L1 截断不修改短内容
class TestToolResultNoTruncationForShortContent:
    """**Validates: Requirements 3.1**

    For any string content with length ≤ tool_result_max_chars,
    cap_tool_result should return the original content unchanged.
    """

    @given(
        max_chars=st.integers(min_value=1, max_value=8000),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_short_content_returned_unchanged(
        self,
        max_chars: int,
        data: st.DataObject,
    ) -> None:
        # Generate content that does NOT exceed max_chars
        content = data.draw(st.text(min_size=0, max_size=min(max_chars, 8000)))

        config = ToolResultGuardConfig(tool_result_max_chars=max_chars)
        guard = ToolResultGuard(config)
        result = guard.cap_tool_result(content)

        assert result == content


# ---------------------------------------------------------------------------
# Property 13: L1 工具专属截断阈值
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 13: L1 工具专属截断阈值
class TestToolSpecificOverrides:
    """**Validates: Requirements 3.4, 3.5**

    For tool names in tool_overrides, uses tool-specific limits;
    for others, uses global defaults.
    """

    @given(
        global_max=st.integers(min_value=200, max_value=5000),
        global_head=st.integers(min_value=10, max_value=1500),
        global_tail=st.integers(min_value=10, max_value=1500),
        override_max=st.integers(min_value=200, max_value=5000),
        override_head=st.integers(min_value=10, max_value=1500),
        override_tail=st.integers(min_value=10, max_value=1500),
        override_tool=_tool_names,
        other_tool=_tool_names,
    )
    @settings(max_examples=100)
    def test_overrides_used_for_matching_tool(
        self,
        global_max: int,
        global_head: int,
        global_tail: int,
        override_max: int,
        override_head: int,
        override_tail: int,
        override_tool: str,
        other_tool: str,
    ) -> None:
        # Ensure the two tool names are different
        if other_tool == override_tool:
            other_tool = override_tool + "_other"

        # Ensure head + tail < max for both configs
        if global_head + global_tail >= global_max:
            global_head = global_max // 3
            global_tail = global_max // 4
        if override_head + override_tail >= override_max:
            override_head = override_max // 3
            override_tail = override_max // 4

        config = ToolResultGuardConfig(
            tool_result_max_chars=global_max,
            head_chars=global_head,
            tail_chars=global_tail,
            tool_overrides={
                override_tool: {
                    "max_chars": override_max,
                    "head_chars": override_head,
                    "tail_chars": override_tail,
                }
            },
        )
        guard = ToolResultGuard(config)

        # Verify _get_limits returns override values for the override tool
        o_max, o_head, o_tail = guard._get_limits(override_tool)
        assert o_max == override_max
        assert o_head == override_head
        assert o_tail == override_tail

        # Verify _get_limits returns global defaults for a different tool
        g_max, g_head, g_tail = guard._get_limits(other_tool)
        assert g_max == global_max
        assert g_head == global_head
        assert g_tail == global_tail

        # Functional check: generate content exceeding override_max and verify
        # the override tool uses override limits
        content_len = override_max + 100
        base = "".join(chr(ord("A") + (i % 26)) for i in range(min(content_len, 1000)))
        content = (base * ((content_len // len(base)) + 1))[:content_len]

        result = guard.cap_tool_result(content, override_tool)
        # If content exceeds override_max, it should be truncated
        assert result[:override_head] == content[:override_head]
        if override_tail > 0:
            assert result[-override_tail:] == content[-override_tail:]
