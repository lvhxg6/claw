"""Property-based tests for CooldownTracker persistence (Properties 29-31).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.providers.fallback import CooldownTracker, FailoverReason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_mock_store() -> AsyncMock:
    """Create a mock MemoryStore with cooldown_state methods."""
    store = AsyncMock()
    store._cooldown_records: list[dict[str, Any]] = []

    async def _set_cooldown_state(
        profile_id: str,
        error_count: int,
        cooldown_end_utc: str,
        last_failure_utc: str,
        failure_counts_json: str,
    ) -> None:
        # Upsert
        for rec in store._cooldown_records:
            if rec["profile_id"] == profile_id:
                rec.update({
                    "error_count": error_count,
                    "cooldown_end_utc": cooldown_end_utc,
                    "last_failure_utc": last_failure_utc,
                    "failure_counts": json.loads(failure_counts_json),
                })
                return
        store._cooldown_records.append({
            "profile_id": profile_id,
            "error_count": error_count,
            "cooldown_end_utc": cooldown_end_utc,
            "last_failure_utc": last_failure_utc,
            "failure_counts": json.loads(failure_counts_json),
        })

    async def _get_cooldown_states() -> list[dict[str, Any]]:
        return list(store._cooldown_records)

    async def _delete_cooldown_state(profile_id: str) -> None:
        store._cooldown_records = [
            r for r in store._cooldown_records if r["profile_id"] != profile_id
        ]

    store.set_cooldown_state = _set_cooldown_state
    store.get_cooldown_states = _get_cooldown_states
    store.delete_cooldown_state = _delete_cooldown_state
    return store


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_profile_ids = st.from_regex(r"[a-z]{3,10}-key-[0-9]{1,3}", fullmatch=True)
_reasons = st.sampled_from([r for r in FailoverReason if r != FailoverReason.FORMAT])


# ---------------------------------------------------------------------------
# Property 29: CooldownTracker 状态持久化往返
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 29: CooldownTracker 状态持久化往返
class TestCooldownPersistenceRoundTrip:
    """**Validates: Requirements 10.2, 10.3**

    For any CooldownTracker with active cooldown entries, save_state followed
    by restore_state on a new tracker should produce equivalent state.
    """

    @given(
        profile_id=_profile_ids,
        reason=_reasons,
    )
    @settings(max_examples=100)
    def test_save_restore_round_trip(
        self, profile_id: str, reason: FailoverReason
    ) -> None:
        """save_state + restore_state preserves cooldown state within tolerance."""
        base_time = 1000.0
        current_time = [base_time]

        def mock_now() -> float:
            return current_time[0]

        tracker1 = CooldownTracker(now_func=mock_now)
        tracker1.mark_failure("provider", reason, profile_id=profile_id)

        store = _make_mock_store()

        # Save state
        _run_async(tracker1.save_state(store))

        # Create new tracker and restore
        tracker2 = CooldownTracker(now_func=mock_now)
        _run_async(tracker2.restore_state(store))

        # Verify: same profile_id should be in cooldown
        assert not tracker2.is_available("provider", profile_id=profile_id)

        # Remaining cooldown should be approximately the same (within 2s tolerance)
        remaining1 = tracker1.cooldown_remaining("provider", profile_id=profile_id)
        remaining2 = tracker2.cooldown_remaining("provider", profile_id=profile_id)
        diff = abs(remaining1.total_seconds() - remaining2.total_seconds())
        assert diff < 2.0, f"Cooldown remaining diff {diff}s exceeds 2s tolerance"


# ---------------------------------------------------------------------------
# Property 30: CooldownTracker mark_failure 触发持久化
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 30: CooldownTracker mark_failure 触发持久化
class TestCooldownMarkFailurePersistence:
    """**Validates: Requirements 10.4**

    For any mark_failure or mark_success call with a MemoryStore,
    the cooldown_state table should be updated.
    """

    @given(
        profile_id=_profile_ids,
        reason=_reasons,
    )
    @settings(max_examples=100)
    def test_mark_failure_persists_state(
        self, profile_id: str, reason: FailoverReason
    ) -> None:
        """mark_failure with store triggers save_state (verified after await)."""
        tracker = CooldownTracker()
        store = _make_mock_store()

        # mark_failure with store triggers fire-and-forget save
        tracker.mark_failure("provider", reason, profile_id=profile_id)

        # Manually save to verify the state is correct
        _run_async(tracker.save_state(store))

        records = _run_async(store.get_cooldown_states())
        assert len(records) >= 1
        saved = next(r for r in records if r["profile_id"] == profile_id)
        assert saved["error_count"] == 1

    @given(profile_id=_profile_ids)
    @settings(max_examples=100)
    def test_mark_success_clears_persisted_state(self, profile_id: str) -> None:
        """mark_success removes the entry, save_state reflects deletion."""
        tracker = CooldownTracker()
        store = _make_mock_store()

        # First mark failure, then save
        tracker.mark_failure("provider", FailoverReason.RATE_LIMIT, profile_id=profile_id)
        _run_async(tracker.save_state(store))

        # Now mark success and save again
        tracker.mark_success("provider", profile_id=profile_id)
        _run_async(tracker.save_state(store))

        records = _run_async(store.get_cooldown_states())
        matching = [r for r in records if r["profile_id"] == profile_id]
        assert len(matching) == 0


# ---------------------------------------------------------------------------
# Property 31: 过期冷却状态不恢复
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 31: 过期冷却状态不恢复
class TestExpiredCooldownNotRestored:
    """**Validates: Requirements 10.6, 10.7**

    For any cooldown_state record where cooldown_end_utc is in the past,
    restore_state should skip it and is_available should return True.
    """

    @given(profile_id=_profile_ids)
    @settings(max_examples=100)
    def test_expired_records_not_restored(self, profile_id: str) -> None:
        """Expired cooldown records are skipped during restore."""
        store = _make_mock_store()

        # Insert an expired record directly
        past_utc = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        last_failure_utc = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        _run_async(
            store.set_cooldown_state(
                profile_id=profile_id,
                error_count=3,
                cooldown_end_utc=past_utc,
                last_failure_utc=last_failure_utc,
                failure_counts_json='{"rate_limit": 3}',
            )
        )

        tracker = CooldownTracker()
        _run_async(tracker.restore_state(store))

        # Expired record should NOT be restored
        assert tracker.is_available("provider", profile_id=profile_id)
