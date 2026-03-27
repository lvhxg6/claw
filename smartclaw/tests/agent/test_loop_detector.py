"""Unit tests for LoopDetector and LoopStatus."""

from __future__ import annotations

import hashlib
import json

from smartclaw.agent.loop_detector import LoopDetector, LoopStatus


class TestLoopStatus:
    """Test LoopStatus enum values."""

    def test_ok_value(self) -> None:
        assert LoopStatus.OK == "ok"

    def test_warn_value(self) -> None:
        assert LoopStatus.WARN == "warn"

    def test_stop_value(self) -> None:
        assert LoopStatus.STOP == "stop"

    def test_is_str_subclass(self) -> None:
        assert isinstance(LoopStatus.OK, str)


class TestLoopDetectorDefaults:
    """Test LoopDetector default construction parameters."""

    def test_default_window_size(self) -> None:
        ld = LoopDetector()
        assert ld._window_size == 20

    def test_default_warn_threshold(self) -> None:
        ld = LoopDetector()
        assert ld._warn_threshold == 3

    def test_default_stop_threshold(self) -> None:
        ld = LoopDetector()
        assert ld._stop_threshold == 5

    def test_custom_parameters(self) -> None:
        ld = LoopDetector(window_size=10, warn_threshold=2, stop_threshold=4)
        assert ld._window_size == 10
        assert ld._warn_threshold == 2
        assert ld._stop_threshold == 4

    def test_empty_window_on_init(self) -> None:
        ld = LoopDetector()
        assert len(ld._window) == 0


class TestComputeHash:
    """Test LoopDetector.compute_hash static method."""

    def test_returns_16_char_hex(self) -> None:
        h = LoopDetector.compute_hash("search", {"q": "hello"})
        assert len(h) == 16
        # Verify all chars are valid hex
        int(h, 16)

    def test_deterministic(self) -> None:
        h1 = LoopDetector.compute_hash("search", {"q": "hello"})
        h2 = LoopDetector.compute_hash("search", {"q": "hello"})
        assert h1 == h2

    def test_matches_sha256_spec(self) -> None:
        tool_name = "search"
        tool_args = {"q": "hello", "limit": 10}
        expected_payload = json.dumps(
            {"name": tool_name, "args": tool_args}, sort_keys=True
        )
        expected = hashlib.sha256(expected_payload.encode()).hexdigest()[:16]
        assert LoopDetector.compute_hash(tool_name, tool_args) == expected

    def test_different_args_different_hash(self) -> None:
        h1 = LoopDetector.compute_hash("search", {"q": "hello"})
        h2 = LoopDetector.compute_hash("search", {"q": "world"})
        assert h1 != h2

    def test_different_names_different_hash(self) -> None:
        h1 = LoopDetector.compute_hash("search", {"q": "hello"})
        h2 = LoopDetector.compute_hash("fetch", {"q": "hello"})
        assert h1 != h2

    def test_sort_keys_order_independent(self) -> None:
        h1 = LoopDetector.compute_hash("tool", {"a": 1, "b": 2})
        h2 = LoopDetector.compute_hash("tool", {"b": 2, "a": 1})
        assert h1 == h2


class TestRecord:
    """Test LoopDetector.record method."""

    def test_first_call_returns_ok(self) -> None:
        ld = LoopDetector()
        status = ld.record("search", {"q": "hello"})
        assert status == LoopStatus.OK

    def test_below_warn_returns_ok(self) -> None:
        ld = LoopDetector(warn_threshold=3, stop_threshold=5)
        ld.record("search", {"q": "hello"})
        status = ld.record("search", {"q": "hello"})
        assert status == LoopStatus.OK

    def test_at_warn_threshold_returns_warn(self) -> None:
        ld = LoopDetector(warn_threshold=3, stop_threshold=5)
        for _ in range(2):
            ld.record("search", {"q": "hello"})
        status = ld.record("search", {"q": "hello"})
        assert status == LoopStatus.WARN

    def test_between_warn_and_stop_returns_warn(self) -> None:
        ld = LoopDetector(warn_threshold=3, stop_threshold=5)
        for _ in range(3):
            ld.record("search", {"q": "hello"})
        status = ld.record("search", {"q": "hello"})
        assert status == LoopStatus.WARN

    def test_at_stop_threshold_returns_stop(self) -> None:
        ld = LoopDetector(warn_threshold=3, stop_threshold=5)
        for _ in range(4):
            ld.record("search", {"q": "hello"})
        status = ld.record("search", {"q": "hello"})
        assert status == LoopStatus.STOP

    def test_window_bounded_by_window_size(self) -> None:
        ld = LoopDetector(window_size=5)
        for i in range(10):
            ld.record("tool", {"i": i})
        assert len(ld._window) == 5

    def test_sliding_window_evicts_old_entries(self) -> None:
        """After filling the window with different calls, old hashes are evicted."""
        ld = LoopDetector(window_size=3, warn_threshold=2, stop_threshold=3)
        # Fill window: [A, B, C]
        ld.record("a", {})
        ld.record("b", {})
        ld.record("c", {})
        # Now add A again — window becomes [B, C, A], count(A)=1 → OK
        status = ld.record("a", {})
        assert status == LoopStatus.OK

    def test_mixed_calls_independent_tracking(self) -> None:
        ld = LoopDetector(warn_threshold=2, stop_threshold=3)
        ld.record("search", {"q": "a"})
        ld.record("fetch", {"url": "b"})
        ld.record("search", {"q": "a"})
        # search-a count = 2 → WARN
        assert ld._window.count(LoopDetector.compute_hash("search", {"q": "a"})) == 2
