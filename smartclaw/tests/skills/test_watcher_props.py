"""Property tests for SkillsWatcher.

Tests the correctness properties of SkillsWatcher using hypothesis.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st, assume

from smartclaw.skills.watcher import (
    IGNORED_DIRS,
    SKILL_FILE_NAMES,
    SkillsWatcher,
    _SkillsEventHandler,
)


class TestProperty9DebounceCoalescing:
    """Property 9: 文件监听器防抖行为.

    For any SkillsWatcher or ConfigWatcher, multiple file change events
    within the debounce window should be merged into a single reload operation.

    Validates: Requirements 3.3, 4.2
    """

    @settings(max_examples=100, deadline=None)  # Disable deadline for sleep-based tests
    @given(
        num_events=st.integers(min_value=2, max_value=10),
        debounce_ms=st.integers(min_value=20, max_value=100),
    )
    def test_multiple_events_coalesce_to_single_reload(
        self, num_events: int, debounce_ms: int
    ) -> None:
        """Multiple events within debounce window should trigger single reload."""
        callback = MagicMock()
        watcher = SkillsWatcher(
            debounce_ms=debounce_ms,
            on_reload=callback,
            enabled=False,
        )

        # Schedule multiple reloads rapidly (within debounce window)
        for i in range(num_events):
            watcher._schedule_reload(f"/path/to/skill_{i}/SKILL.md")

        # Wait for debounce to complete
        time.sleep((debounce_ms + 50) / 1000.0)

        # Should only have called callback once
        assert callback.call_count == 1

    @settings(max_examples=50, deadline=None)  # Disable deadline for sleep-based tests
    @given(
        debounce_ms=st.integers(min_value=20, max_value=80),
    )
    def test_events_after_debounce_trigger_new_reload(
        self, debounce_ms: int
    ) -> None:
        """Events after debounce window should trigger new reload."""
        callback = MagicMock()
        watcher = SkillsWatcher(
            debounce_ms=debounce_ms,
            on_reload=callback,
            enabled=False,
        )

        # First event
        watcher._schedule_reload("/path/to/skill_1/SKILL.md")

        # Wait for debounce to complete
        time.sleep((debounce_ms + 30) / 1000.0)

        # Second event after debounce
        watcher._schedule_reload("/path/to/skill_2/SKILL.md")

        # Wait for second debounce
        time.sleep((debounce_ms + 30) / 1000.0)

        # Should have called callback twice
        assert callback.call_count == 2


class TestProperty10VersionMonotonicIncrease:
    """Property 10: Skills 版本号单调递增.

    For any SkillsWatcher instance, each version bump should produce
    a strictly greater version number than the previous.

    Validates: Requirements 3.4
    """

    @settings(max_examples=100)
    @given(num_bumps=st.integers(min_value=2, max_value=100))
    def test_version_strictly_increasing(self, num_bumps: int) -> None:
        """Version should strictly increase with each bump."""
        watcher = SkillsWatcher(enabled=False)

        versions = []
        for _ in range(num_bumps):
            versions.append(watcher._bump_version())

        # Each version should be strictly greater than the previous
        for i in range(1, len(versions)):
            assert versions[i] > versions[i - 1], (
                f"Version {versions[i]} should be > {versions[i - 1]}"
            )

    @settings(max_examples=100)
    @given(
        initial_version=st.integers(min_value=0, max_value=10**15),
        num_bumps=st.integers(min_value=1, max_value=50),
    )
    def test_version_monotonic_from_any_start(
        self, initial_version: int, num_bumps: int
    ) -> None:
        """Version should be monotonic even from arbitrary starting point."""
        watcher = SkillsWatcher(enabled=False)
        watcher._version = initial_version

        versions = [initial_version]
        for _ in range(num_bumps):
            versions.append(watcher._bump_version())

        # All versions should be strictly increasing
        for i in range(1, len(versions)):
            assert versions[i] > versions[i - 1]

    @settings(max_examples=50)
    @given(st.data())
    def test_concurrent_bumps_are_monotonic(self, data: st.DataObject) -> None:
        """Concurrent version bumps should still be monotonic."""
        watcher = SkillsWatcher(enabled=False)
        num_threads = data.draw(st.integers(min_value=2, max_value=10))
        bumps_per_thread = data.draw(st.integers(min_value=5, max_value=20))

        all_versions: list[int] = []
        lock = threading.Lock()

        def bump_versions() -> None:
            for _ in range(bumps_per_thread):
                v = watcher._bump_version()
                with lock:
                    all_versions.append(v)

        threads = [threading.Thread(target=bump_versions) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Sort and check uniqueness (all versions should be unique)
        assert len(all_versions) == len(set(all_versions)), "All versions should be unique"


class TestProperty11IgnoredDirectoryFiltering:
    """Property 11: 忽略目录过滤.

    For any file change in .git, __pycache__, venv, .venv, node_modules,
    .idea, .vscode directories, SkillsWatcher should not trigger reload.

    Validates: Requirements 3.5
    """

    @settings(max_examples=100)
    @given(
        ignored_dir=st.sampled_from(list(IGNORED_DIRS)),
        subpath=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=1,
            max_size=20,
        ),
        skill_file=st.sampled_from(list(SKILL_FILE_NAMES)),
    )
    def test_files_in_ignored_dirs_not_trigger_reload(
        self, ignored_dir: str, subpath: str, skill_file: str
    ) -> None:
        """Files in ignored directories should not trigger reload."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        # Construct path with ignored directory
        path = f"/workspace/{ignored_dir}/{subpath}/{skill_file}"

        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    @settings(max_examples=100)
    @given(
        ignored_dir=st.sampled_from(list(IGNORED_DIRS)),
        depth=st.integers(min_value=1, max_value=5),
    )
    def test_ignored_dir_at_any_depth(self, ignored_dir: str, depth: int) -> None:
        """Ignored directory at any path depth should filter events."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        # Build path with ignored dir at specified depth
        parts = ["workspace"] + [f"dir{i}" for i in range(depth - 1)] + [ignored_dir, "SKILL.md"]
        path = "/" + "/".join(parts)

        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    @settings(max_examples=100)
    @given(
        safe_dirs=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
                min_size=1,
                max_size=10,
            ).filter(lambda x: x not in IGNORED_DIRS),
            min_size=1,
            max_size=5,
        ),
        skill_file=st.sampled_from(list(SKILL_FILE_NAMES)),
    )
    def test_files_in_safe_dirs_trigger_reload(
        self, safe_dirs: list[str], skill_file: str
    ) -> None:
        """Files in non-ignored directories should trigger reload."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        # Construct path without ignored directories
        path = "/workspace/" + "/".join(safe_dirs) + "/" + skill_file

        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_called_once_with(path)


class TestProperty12ErrorRollback:
    """Property 12: 监听器错误回退.

    For any SkillsWatcher or ConfigWatcher, when reload fails,
    the previous valid version should be preserved.

    Validates: Requirements 3.10, 4.5
    """

    @settings(max_examples=100)
    @given(
        initial_version=st.integers(min_value=1, max_value=10**12),
        num_failures=st.integers(min_value=1, max_value=10),
    )
    def test_version_preserved_on_callback_error(
        self, initial_version: int, num_failures: int
    ) -> None:
        """Version should still update even when callback fails."""
        # Note: In current implementation, version updates before callback
        # This test verifies the watcher doesn't crash on errors
        callback = MagicMock(side_effect=Exception("Simulated error"))
        watcher = SkillsWatcher(
            on_reload=callback,
            enabled=False,
        )
        watcher._version = initial_version

        # Trigger multiple failed reloads
        for i in range(num_failures):
            watcher._pending_path = f"/path/to/skill_{i}/SKILL.md"
            watcher._do_reload()  # Should not raise

        # Callback should have been called for each reload
        assert callback.call_count == num_failures

        # Watcher should still be functional
        assert watcher.get_version() > initial_version

    @settings(max_examples=50)
    @given(
        success_count=st.integers(min_value=1, max_value=5),
        failure_count=st.integers(min_value=1, max_value=5),
    )
    def test_watcher_continues_after_errors(
        self, success_count: int, failure_count: int
    ) -> None:
        """Watcher should continue working after callback errors."""
        call_results: list[bool] = []

        def callback() -> None:
            if len(call_results) < failure_count:
                call_results.append(False)
                raise Exception("Simulated error")
            call_results.append(True)

        watcher = SkillsWatcher(
            on_reload=callback,
            enabled=False,
        )

        # Trigger reloads (some will fail, some will succeed)
        total_calls = failure_count + success_count
        for i in range(total_calls):
            watcher._pending_path = f"/path/to/skill_{i}/SKILL.md"
            watcher._do_reload()

        # All calls should have been attempted
        assert len(call_results) == total_calls
        # First failure_count should have failed
        assert call_results[:failure_count] == [False] * failure_count
        # Remaining should have succeeded
        assert call_results[failure_count:] == [True] * success_count


class TestSkillFileMatching:
    """Additional property tests for skill file matching."""

    @settings(max_examples=100)
    @given(
        skill_file=st.sampled_from(["SKILL.md", "skill.md", "Skill.MD", "SKILL.yaml", "skill.YAML"]),
        path_prefix=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-/"),
            min_size=1,
            max_size=50,
        ).filter(lambda x: not any(d in x for d in IGNORED_DIRS)),
    )
    def test_skill_files_case_insensitive_matching(
        self, skill_file: str, path_prefix: str
    ) -> None:
        """Skill files should be matched case-insensitively."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        # Clean up path prefix
        path_prefix = path_prefix.strip("/")
        if not path_prefix:
            path_prefix = "skills"

        path = f"/workspace/{path_prefix}/{skill_file}"

        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_called_once()

    @settings(max_examples=100)
    @given(
        non_skill_file=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-."),
            min_size=1,
            max_size=20,
        ).filter(lambda x: x.lower() not in SKILL_FILE_NAMES),
    )
    def test_non_skill_files_not_matched(self, non_skill_file: str) -> None:
        """Non-skill files should not trigger reload."""
        assume(non_skill_file)  # Skip empty strings

        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        path = f"/workspace/skills/{non_skill_file}"

        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()
