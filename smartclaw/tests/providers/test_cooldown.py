"""Unit tests for CooldownTracker.

Tests: initial availability, cooldown after failure, success reset,
multi-provider isolation, concurrent safety, exponential backoff values.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from smartclaw.providers.fallback import CooldownTracker, FailoverReason


class TestCooldownInitial:
    """Fresh tracker — all providers available."""

    def test_unknown_provider_available(self) -> None:
        tracker = CooldownTracker()
        assert tracker.is_available("openai")

    def test_unknown_provider_zero_remaining(self) -> None:
        tracker = CooldownTracker()
        assert tracker.cooldown_remaining("openai") == timedelta(0)


class TestCooldownAfterFailure:
    """After mark_failure, provider should be in cooldown."""

    def test_not_available_after_failure(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        assert not tracker.is_available("openai")

    def test_remaining_positive_after_failure(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        assert tracker.cooldown_remaining("openai") > timedelta(0)

    def test_available_after_cooldown_expires(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        # Standard 1st failure = 60s cooldown
        t = 61.0
        assert tracker.is_available("openai")


class TestCooldownSuccessReset:
    """mark_success resets cooldown completely."""

    def test_available_after_success(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        assert not tracker.is_available("openai")
        tracker.mark_success("openai")
        assert tracker.is_available("openai")

    def test_zero_remaining_after_success(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        tracker.mark_success("openai")
        assert tracker.cooldown_remaining("openai") == timedelta(0)


class TestCooldownMultiProvider:
    """Providers are tracked independently."""

    def test_isolated_providers(self) -> None:
        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
        assert not tracker.is_available("openai")
        assert tracker.is_available("anthropic")


class TestCooldownExponentialBackoff:
    """Verify exponential backoff values match the spec."""

    def test_standard_backoff_1_error(self) -> None:
        # 1 error → 60s
        secs = CooldownTracker._compute_cooldown(1, FailoverReason.RATE_LIMIT)
        assert secs == 60.0

    def test_standard_backoff_2_errors(self) -> None:
        # 2 errors → 300s (5 min)
        secs = CooldownTracker._compute_cooldown(2, FailoverReason.RATE_LIMIT)
        assert secs == 300.0

    def test_standard_backoff_3_errors(self) -> None:
        # 3 errors → 1500s (25 min)
        secs = CooldownTracker._compute_cooldown(3, FailoverReason.RATE_LIMIT)
        assert secs == 1500.0

    def test_standard_backoff_4_errors_capped(self) -> None:
        # 4+ errors → 3600s (1 hour cap)
        secs = CooldownTracker._compute_cooldown(4, FailoverReason.RATE_LIMIT)
        assert secs == 3600.0

    def test_billing_backoff_1_error(self) -> None:
        # 1 error → 5h = 18000s
        secs = CooldownTracker._compute_cooldown(1, FailoverReason.AUTH)
        assert secs == 18000.0

    def test_billing_backoff_2_errors(self) -> None:
        # 2 errors → 10h = 36000s
        secs = CooldownTracker._compute_cooldown(2, FailoverReason.AUTH)
        assert secs == 36000.0

    def test_billing_backoff_3_errors(self) -> None:
        # 3 errors → 20h = 72000s
        secs = CooldownTracker._compute_cooldown(3, FailoverReason.AUTH)
        assert secs == 72000.0

    def test_billing_backoff_4_errors_capped(self) -> None:
        # 4 errors → 24h cap = 86400s
        secs = CooldownTracker._compute_cooldown(4, FailoverReason.AUTH)
        assert secs == 86400.0


class TestCooldownConcurrency:
    """Thread-safety smoke test."""

    def test_concurrent_mark_failure(self) -> None:
        tracker = CooldownTracker()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(100):
                    tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)
                    tracker.is_available("openai")
                    tracker.cooldown_remaining("openai")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access errors: {errors}"
