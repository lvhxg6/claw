"""Unit tests for SkillsWatcher.

Tests the SkillsWatcher class for SKILL.md hot-reload functionality.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smartclaw.skills.watcher import (
    DEFAULT_DEBOUNCE_MS,
    IGNORED_DIRS,
    SKILL_FILE_NAMES,
    WATCHDOG_AVAILABLE,
    SkillsWatcher,
    _SkillsEventHandler,
)


class TestSkillsWatcherInit:
    """Tests for SkillsWatcher initialization."""

    def test_init_with_defaults(self) -> None:
        """Should initialize with default values."""
        watcher = SkillsWatcher(enabled=False)

        assert watcher.workspace_dir is None
        assert watcher.global_dir == Path("~/.smartclaw/skills").expanduser().resolve()
        assert watcher.enabled is False
        assert watcher.running is False
        assert watcher.get_version() == 0

    def test_init_with_workspace_dir(self, tmp_path: Path) -> None:
        """Should set workspace skills directory correctly."""
        watcher = SkillsWatcher(
            workspace_dir=str(tmp_path),
            enabled=False,
        )

        # Workspace dir should be {workspace}/skills/
        expected = tmp_path.resolve() / "skills"
        assert watcher.workspace_dir == expected

    def test_init_with_custom_global_dir(self, tmp_path: Path) -> None:
        """Should set custom global directory correctly."""
        global_dir = tmp_path / "custom_skills"
        watcher = SkillsWatcher(
            global_dir=str(global_dir),
            enabled=False,
        )

        assert watcher.global_dir == global_dir.resolve()

    def test_init_with_custom_debounce(self) -> None:
        """Should accept custom debounce time."""
        watcher = SkillsWatcher(
            debounce_ms=500,
            enabled=False,
        )

        assert watcher._debounce_ms == 500

    def test_init_with_callback(self) -> None:
        """Should accept reload callback."""
        callback = MagicMock()
        watcher = SkillsWatcher(
            on_reload=callback,
            enabled=False,
        )

        assert watcher._on_reload is callback


class TestSkillsWatcherStartStop:
    """Tests for SkillsWatcher start/stop lifecycle."""

    def test_start_when_disabled(self) -> None:
        """Should not start when disabled."""
        watcher = SkillsWatcher(enabled=False)
        watcher.start()

        assert watcher.running is False

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_start_creates_observer(self, tmp_path: Path) -> None:
        """Should create observer when started."""
        # Create directories
        workspace_skills = tmp_path / "workspace" / "skills"
        workspace_skills.mkdir(parents=True)
        global_skills = tmp_path / "global_skills"
        global_skills.mkdir(parents=True)

        watcher = SkillsWatcher(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(global_skills),
            enabled=True,
        )

        try:
            watcher.start()
            assert watcher.running is True
            assert watcher._observer is not None
        finally:
            watcher.stop()

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_start_twice_is_idempotent(self, tmp_path: Path) -> None:
        """Should not start twice."""
        global_skills = tmp_path / "global_skills"
        global_skills.mkdir(parents=True)

        watcher = SkillsWatcher(
            global_dir=str(global_skills),
            enabled=True,
        )

        try:
            watcher.start()
            observer1 = watcher._observer
            watcher.start()  # Second start should be no-op
            assert watcher._observer is observer1
        finally:
            watcher.stop()

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_stop_cleans_up(self, tmp_path: Path) -> None:
        """Should clean up resources on stop."""
        global_skills = tmp_path / "global_skills"
        global_skills.mkdir(parents=True)

        watcher = SkillsWatcher(
            global_dir=str(global_skills),
            enabled=True,
        )

        watcher.start()
        assert watcher.running is True

        watcher.stop()
        assert watcher.running is False
        assert watcher._observer is None

    def test_stop_when_not_running(self) -> None:
        """Should handle stop when not running."""
        watcher = SkillsWatcher(enabled=False)
        watcher.stop()  # Should not raise

        assert watcher.running is False


class TestSkillsWatcherVersion:
    """Tests for SkillsWatcher version management."""

    def test_initial_version_is_zero(self) -> None:
        """Should start with version 0."""
        watcher = SkillsWatcher(enabled=False)
        assert watcher.get_version() == 0

    def test_bump_version_increases(self) -> None:
        """Should increase version on bump."""
        watcher = SkillsWatcher(enabled=False)

        v1 = watcher._bump_version()
        v2 = watcher._bump_version()
        v3 = watcher._bump_version()

        assert v1 > 0
        assert v2 > v1
        assert v3 > v2

    def test_bump_version_is_timestamp_based(self) -> None:
        """Should use timestamp-based versioning."""
        watcher = SkillsWatcher(enabled=False)

        before = int(time.time() * 1000)
        version = watcher._bump_version()
        after = int(time.time() * 1000)

        # Version should be close to current timestamp
        assert before <= version <= after + 1

    def test_bump_version_monotonic(self) -> None:
        """Should ensure monotonic increase even with same timestamp."""
        watcher = SkillsWatcher(enabled=False)

        # Force same timestamp scenario
        watcher._version = int(time.time() * 1000) + 10000

        v1 = watcher._bump_version()
        v2 = watcher._bump_version()

        assert v2 > v1


class TestSkillsWatcherDebounce:
    """Tests for SkillsWatcher debounce mechanism."""

    def test_schedule_reload_creates_timer(self) -> None:
        """Should create timer on schedule."""
        watcher = SkillsWatcher(
            debounce_ms=100,
            enabled=False,
        )

        watcher._schedule_reload("/path/to/SKILL.md")

        assert watcher._timer is not None
        assert watcher._pending_path == "/path/to/SKILL.md"

        # Clean up
        watcher._timer.cancel()

    def test_schedule_reload_cancels_previous_timer(self) -> None:
        """Should cancel previous timer on new schedule."""
        watcher = SkillsWatcher(
            debounce_ms=1000,  # Long debounce to prevent execution
            enabled=False,
        )

        watcher._schedule_reload("/path/to/first.md")
        timer1 = watcher._timer

        watcher._schedule_reload("/path/to/second.md")
        timer2 = watcher._timer

        assert timer1 is not timer2
        assert watcher._pending_path == "/path/to/second.md"

        # Clean up
        if watcher._timer:
            watcher._timer.cancel()

    def test_do_reload_invokes_callback(self) -> None:
        """Should invoke callback on reload."""
        callback = MagicMock()
        watcher = SkillsWatcher(
            on_reload=callback,
            enabled=False,
        )

        watcher._pending_path = "/path/to/SKILL.md"
        watcher._do_reload()

        callback.assert_called_once()

    def test_do_reload_updates_version(self) -> None:
        """Should update version on reload."""
        watcher = SkillsWatcher(enabled=False)

        initial_version = watcher.get_version()
        watcher._pending_path = "/path/to/SKILL.md"
        watcher._do_reload()

        assert watcher.get_version() > initial_version

    def test_do_reload_handles_callback_error(self) -> None:
        """Should handle callback errors gracefully."""
        callback = MagicMock(side_effect=Exception("Test error"))
        watcher = SkillsWatcher(
            on_reload=callback,
            enabled=False,
        )

        watcher._pending_path = "/path/to/SKILL.md"
        # Should not raise
        watcher._do_reload()

        callback.assert_called_once()

    def test_debounce_merges_multiple_events(self) -> None:
        """Should merge multiple events within debounce window."""
        callback = MagicMock()
        watcher = SkillsWatcher(
            debounce_ms=50,
            on_reload=callback,
            enabled=False,
        )

        # Schedule multiple reloads quickly
        watcher._schedule_reload("/path/to/first.md")
        watcher._schedule_reload("/path/to/second.md")
        watcher._schedule_reload("/path/to/third.md")

        # Wait for debounce
        time.sleep(0.1)

        # Should only call once
        assert callback.call_count == 1


class TestSkillsEventHandler:
    """Tests for _SkillsEventHandler."""

    def test_ignores_directory_events(self) -> None:
        """Should ignore directory events."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = True
        event.src_path = "/path/to/skills"

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    def test_ignores_non_skill_files(self) -> None:
        """Should ignore non-skill files."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/README.md"

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    def test_handles_skill_md_file(self) -> None:
        """Should handle SKILL.md file changes."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/skills/my-skill/SKILL.md"

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_called_once_with("/path/to/skills/my-skill/SKILL.md")

    def test_handles_skill_yaml_file(self) -> None:
        """Should handle skill.yaml file changes."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/skills/my-skill/skill.yaml"

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_called_once_with("/path/to/skills/my-skill/skill.yaml")

    def test_case_insensitive_file_matching(self) -> None:
        """Should match skill files case-insensitively."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        for filename in ["SKILL.MD", "skill.md", "Skill.Md", "SKILL.YAML", "skill.YAML"]:
            event = MagicMock()
            event.is_directory = False
            event.src_path = f"/path/to/skills/my-skill/{filename}"

            with patch.object(watcher, "_schedule_reload") as mock_schedule:
                handler._handle(event)
                mock_schedule.assert_called_once()

    @pytest.mark.parametrize("ignored_dir", list(IGNORED_DIRS))
    def test_ignores_files_in_ignored_dirs(self, ignored_dir: str) -> None:
        """Should ignore files in ignored directories."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = f"/path/to/{ignored_dir}/SKILL.md"

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    def test_on_created_calls_handle(self) -> None:
        """Should call _handle on created event."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/SKILL.md"

        with patch.object(handler, "_handle") as mock_handle:
            handler.on_created(event)
            mock_handle.assert_called_once_with(event)

    def test_on_modified_calls_handle(self) -> None:
        """Should call _handle on modified event."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/SKILL.md"

        with patch.object(handler, "_handle") as mock_handle:
            handler.on_modified(event)
            mock_handle.assert_called_once_with(event)

    def test_on_deleted_calls_handle(self) -> None:
        """Should call _handle on deleted event."""
        watcher = SkillsWatcher(enabled=False)
        handler = _SkillsEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/SKILL.md"

        with patch.object(handler, "_handle") as mock_handle:
            handler.on_deleted(event)
            mock_handle.assert_called_once_with(event)


class TestSkillsWatcherConstants:
    """Tests for module constants."""

    def test_default_debounce_ms(self) -> None:
        """Should have correct default debounce value."""
        assert DEFAULT_DEBOUNCE_MS == 250

    def test_ignored_dirs_contains_expected(self) -> None:
        """Should contain expected ignored directories."""
        expected = {".git", "__pycache__", "venv", ".venv", "node_modules", ".idea", ".vscode"}
        assert IGNORED_DIRS == expected

    def test_skill_file_names(self) -> None:
        """Should contain expected skill file names."""
        assert "skill.md" in SKILL_FILE_NAMES
        assert "skill.yaml" in SKILL_FILE_NAMES
