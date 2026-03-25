"""Property-based tests for CooldownTracker.

# Feature: smartclaw-llm-agent-core
# Property 8
"""

from __future__ import annotations

from datetime import timedelta

import hypothesis.strategies as st
from hypothesis import given, settings

from smartclaw.providers.fallback import CooldownTracker, FailoverReason

_provider_st = st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N")))  # type: ignore[arg-type]
_failure_count_st = st.integers(min_value=1, max_value=10)
_reason_st = st.sampled_from(list(FailoverReason))


# ---------------------------------------------------------------------------
# Property 8: Cooldown tracker round-trip (failure then success resets)
# ---------------------------------------------------------------------------


class TestCooldownRoundTrip:
    """Property 8: Cooldown tracker round-trip (failure then success resets).

    **Validates: Requirements 3.5, 3.7**

    For any provider name string, after calling mark_failure() N times (N >= 1),
    is_available() should return False (provider in cooldown). After subsequently
    calling mark_success(), is_available() should return True and
    cooldown_remaining() should return timedelta(0).
    """

    @settings(max_examples=100)
    @given(
        provider=_provider_st,
        n_failures=_failure_count_st,
        reason=_reason_st,
    )
    def test_failure_then_success_resets(
        self,
        provider: str,
        n_failures: int,
        reason: FailoverReason,
    ) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 8: Cooldown tracker round-trip (failure then success resets)"""
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)

        # Apply N failures
        for _ in range(n_failures):
            tracker.mark_failure(provider, reason)

        # Provider should be in cooldown (time hasn't advanced)
        assert not tracker.is_available(provider), (
            f"Provider '{provider}' should be in cooldown after {n_failures} failure(s)"
        )
        assert tracker.cooldown_remaining(provider) > timedelta(0)

        # Reset via success
        tracker.mark_success(provider)

        # Provider should be available again
        assert tracker.is_available(provider), (
            f"Provider '{provider}' should be available after mark_success()"
        )
        assert tracker.cooldown_remaining(provider) == timedelta(0)
