"""Unit tests for ConfigWatcher.

Tests the ConfigWatcher class for config.yaml hot-reload functionality.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from smartclaw.config.watcher import (
    DEFAULT_DEBOUNCE_MS,
    HOT_RELOAD_KEYS,
    RESTART_REQUIRED_KEYS,
    WATCHDOG_AVAILABLE,
    ConfigWatcher,
    _ConfigEventHandler,
)


class TestConfigWatcherInit:
    """Tests for ConfigWatcher initialization."""

    def test_init_with_defaults(self) -> None:
        """Should initialize with default values."""
        watcher = ConfigWatcher(enabled=False)

        assert watcher.config_path == Path("config.yaml").expanduser().resolve()
        assert watcher.enabled is False
        assert watcher.running is False
        assert watcher.current_config == {}

    def test_init_with_custom_path(self, tmp_path: Path) -> None:
        """Should set custom config path correctly."""
        config_path = tmp_path / "custom_config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )

        assert watcher.config_path == config_path.resolve()

    def test_init_with_custom_debounce(self) -> None:
        """Should accept custom debounce time."""
        watcher = ConfigWatcher(
            debounce_ms=1000,
            enabled=False,
        )

        assert watcher._debounce_ms == 1000

    def test_init_with_callbacks(self) -> None:
        """Should accept reload callbacks."""
        on_reload = MagicMock()
        on_restart = MagicMock()
        watcher = ConfigWatcher(
            on_reload=on_reload,
            on_restart_required=on_restart,
            enabled=False,
        )

        assert watcher._on_reload is on_reload
        assert watcher._on_restart_required is on_restart


class TestConfigWatcherStartStop:
    """Tests for ConfigWatcher start/stop lifecycle."""

    def test_start_when_disabled(self) -> None:
        """Should not start when disabled."""
        watcher = ConfigWatcher(enabled=False)
        watcher.start()

        assert watcher.running is False

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_start_creates_observer(self, tmp_path: Path) -> None:
        """Should create observer when started."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("providers: {}")

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=True,
        )

        try:
            watcher.start()
            assert watcher.running is True
            assert watcher._observer is not None
        finally:
            watcher.stop()

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_start_loads_initial_config(self, tmp_path: Path) -> None:
        """Should load initial configuration on start."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"providers": {"openai": {}}}))

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=True,
        )

        try:
            watcher.start()
            assert watcher.current_config == {"providers": {"openai": {}}}
        finally:
            watcher.stop()

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_start_twice_is_idempotent(self, tmp_path: Path) -> None:
        """Should not start twice."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("providers: {}")

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=True,
        )

        try:
            watcher.start()
            observer1 = watcher._observer
            watcher.start()
            assert watcher._observer is observer1
        finally:
            watcher.stop()

    @pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not installed")
    def test_stop_cleans_up(self, tmp_path: Path) -> None:
        """Should clean up resources on stop."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("providers: {}")

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=True,
        )

        watcher.start()
        assert watcher.running is True

        watcher.stop()
        assert watcher.running is False
        assert watcher._observer is None

    def test_stop_when_not_running(self) -> None:
        """Should handle stop when not running."""
        watcher = ConfigWatcher(enabled=False)
        watcher.stop()  # Should not raise

        assert watcher.running is False


class TestConfigWatcherValidation:
    """Tests for configuration validation."""

    def test_validate_empty_config(self) -> None:
        """Should accept empty configuration."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({})
        assert errors == []

    def test_validate_non_dict_config(self) -> None:
        """Should reject non-dictionary configuration."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config("invalid")  # type: ignore
        assert "Configuration must be a dictionary" in errors

    def test_validate_invalid_providers(self) -> None:
        """Should reject invalid providers section."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"providers": "invalid"})
        assert "'providers' must be a dictionary" in errors

    def test_validate_invalid_memory_chunk_tokens(self) -> None:
        """Should reject invalid memory.chunk_tokens."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"memory": {"chunk_tokens": -1}})
        assert "'memory.chunk_tokens' must be a positive integer" in errors

    def test_validate_invalid_memory_vector_weight(self) -> None:
        """Should reject invalid memory.vector_weight."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"memory": {"vector_weight": 1.5}})
        assert "'memory.vector_weight' must be between 0 and 1" in errors

    def test_validate_invalid_skills_debounce(self) -> None:
        """Should reject invalid skills.debounce_ms."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"skills": {"debounce_ms": -100}})
        assert "'skills.debounce_ms' must be a non-negative integer" in errors

    def test_validate_invalid_gateway_port(self) -> None:
        """Should reject invalid gateway.port."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"gateway": {"port": 70000}})
        assert "'gateway.port' must be between 1 and 65535" in errors

    def test_validate_invalid_logging_level(self) -> None:
        """Should reject invalid logging.level."""
        watcher = ConfigWatcher(enabled=False)
        errors = watcher._validate_config({"logging": {"level": "INVALID"}})
        assert any("logging.level" in e for e in errors)

    def test_validate_valid_config(self) -> None:
        """Should accept valid configuration."""
        watcher = ConfigWatcher(enabled=False)
        config = {
            "providers": {"openai": {"api_key": "test"}},
            "memory": {"chunk_tokens": 512, "vector_weight": 0.7},
            "skills": {"debounce_ms": 250},
            "gateway": {"host": "localhost", "port": 8080},
            "logging": {"level": "INFO"},
        }
        errors = watcher._validate_config(config)
        assert errors == []


class TestConfigWatcherDiff:
    """Tests for configuration diff computation."""

    def test_diff_no_changes(self) -> None:
        """Should detect no changes."""
        watcher = ConfigWatcher(enabled=False)
        config = {"providers": {"openai": {}}}
        changed, restart = watcher._diff_config(config, config.copy())
        assert changed == set()
        assert restart == set()

    def test_diff_hot_reload_changes(self) -> None:
        """Should detect hot-reloadable changes."""
        watcher = ConfigWatcher(enabled=False)
        old = {"providers": {"openai": {}}}
        new = {"providers": {"anthropic": {}}}
        changed, restart = watcher._diff_config(old, new)
        assert "providers" in changed
        assert restart == set()

    def test_diff_restart_required_changes(self) -> None:
        """Should detect restart-required changes."""
        watcher = ConfigWatcher(enabled=False)
        old = {"gateway": {"host": "localhost", "port": 8080}}
        new = {"gateway": {"host": "localhost", "port": 9090}}
        changed, restart = watcher._diff_config(old, new)
        assert "gateway" in restart or "gateway.port" in restart

    def test_diff_mixed_changes(self) -> None:
        """Should handle mixed changes."""
        watcher = ConfigWatcher(enabled=False)
        old = {
            "providers": {"openai": {}},
            "gateway": {"port": 8080},
        }
        new = {
            "providers": {"anthropic": {}},
            "gateway": {"port": 9090},
        }
        changed, restart = watcher._diff_config(old, new)
        assert "providers" in changed
        assert "gateway" in restart or "gateway.port" in restart

    def test_diff_new_key_added(self) -> None:
        """Should detect new keys."""
        watcher = ConfigWatcher(enabled=False)
        old = {}
        new = {"memory": {"enabled": True}}
        changed, restart = watcher._diff_config(old, new)
        assert "memory" in changed

    def test_diff_key_removed(self) -> None:
        """Should detect removed keys."""
        watcher = ConfigWatcher(enabled=False)
        old = {"memory": {"enabled": True}}
        new = {}
        changed, restart = watcher._diff_config(old, new)
        assert "memory" in changed


class TestConfigWatcherReload:
    """Tests for configuration reload functionality."""

    def test_do_reload_with_valid_config(self, tmp_path: Path) -> None:
        """Should reload valid configuration."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"providers": {"openai": {}}}))

        callback = MagicMock()
        watcher = ConfigWatcher(
            config_path=str(config_path),
            on_reload=callback,
            enabled=False,
        )
        watcher._current_config = {}

        watcher._do_reload()

        assert watcher.current_config == {"providers": {"openai": {}}}
        callback.assert_called_once()

    def test_do_reload_with_invalid_yaml(self, tmp_path: Path) -> None:
        """Should handle invalid YAML gracefully."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("invalid: yaml: content:")

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        watcher._current_config = {"old": "config"}
        watcher._last_valid_config = {"old": "config"}

        watcher._do_reload()

        # Should keep old config
        assert watcher.current_config == {"old": "config"}

    def test_do_reload_with_validation_error(self, tmp_path: Path) -> None:
        """Should reject config with validation errors."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"memory": {"chunk_tokens": -1}}))

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        watcher._current_config = {"old": "config"}

        watcher._do_reload()

        # Should keep old config
        assert watcher.current_config == {"old": "config"}

    def test_do_reload_callback_error_rollback(self, tmp_path: Path) -> None:
        """Should rollback on callback error."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"providers": {"new": {}}}))

        callback = MagicMock(side_effect=Exception("Callback error"))
        watcher = ConfigWatcher(
            config_path=str(config_path),
            on_reload=callback,
            enabled=False,
        )
        watcher._current_config = {"providers": {"old": {}}}

        watcher._do_reload()

        # Should rollback to old config
        assert watcher.current_config == {"providers": {"old": {}}}

    def test_do_reload_notifies_restart_required(self, tmp_path: Path) -> None:
        """Should notify when restart-required keys change."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"gateway": {"port": 9090}}))

        restart_callback = MagicMock()
        watcher = ConfigWatcher(
            config_path=str(config_path),
            on_restart_required=restart_callback,
            enabled=False,
        )
        watcher._current_config = {"gateway": {"port": 8080}}

        watcher._do_reload()

        restart_callback.assert_called_once()

    def test_force_reload(self, tmp_path: Path) -> None:
        """Should force immediate reload."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"providers": {"test": {}}}))

        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )

        watcher.force_reload()

        assert watcher.current_config == {"providers": {"test": {}}}


class TestConfigWatcherDebounce:
    """Tests for ConfigWatcher debounce mechanism."""

    def test_schedule_reload_creates_timer(self) -> None:
        """Should create timer on schedule."""
        watcher = ConfigWatcher(
            debounce_ms=100,
            enabled=False,
        )

        watcher._schedule_reload()

        assert watcher._timer is not None

        # Clean up
        watcher._timer.cancel()

    def test_schedule_reload_cancels_previous_timer(self) -> None:
        """Should cancel previous timer on new schedule."""
        watcher = ConfigWatcher(
            debounce_ms=1000,
            enabled=False,
        )

        watcher._schedule_reload()
        timer1 = watcher._timer

        watcher._schedule_reload()
        timer2 = watcher._timer

        assert timer1 is not timer2

        # Clean up
        if watcher._timer:
            watcher._timer.cancel()

    def test_debounce_merges_multiple_events(self, tmp_path: Path) -> None:
        """Should merge multiple events within debounce window."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"providers": {}}))

        callback = MagicMock()
        watcher = ConfigWatcher(
            config_path=str(config_path),
            debounce_ms=50,
            on_reload=callback,
            enabled=False,
        )
        watcher._current_config = {}

        # Schedule multiple reloads quickly
        watcher._schedule_reload()
        watcher._schedule_reload()
        watcher._schedule_reload()

        # Wait for debounce
        time.sleep(0.1)

        # Should only call once
        assert callback.call_count == 1


class TestConfigEventHandler:
    """Tests for _ConfigEventHandler."""

    def test_ignores_directory_events(self, tmp_path: Path) -> None:
        """Should ignore directory events."""
        config_path = tmp_path / "config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        handler = _ConfigEventHandler(watcher)

        event = MagicMock()
        event.is_directory = True
        event.src_path = str(tmp_path)

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    def test_ignores_other_files(self, tmp_path: Path) -> None:
        """Should ignore non-config files."""
        config_path = tmp_path / "config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        handler = _ConfigEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "other.yaml")

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_not_called()

    def test_handles_config_file_change(self, tmp_path: Path) -> None:
        """Should handle config file changes."""
        config_path = tmp_path / "config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        handler = _ConfigEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(config_path)

        with patch.object(watcher, "_schedule_reload") as mock_schedule:
            handler._handle(event)
            mock_schedule.assert_called_once()

    def test_on_modified_calls_handle(self, tmp_path: Path) -> None:
        """Should call _handle on modified event."""
        config_path = tmp_path / "config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        handler = _ConfigEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(config_path)

        with patch.object(handler, "_handle") as mock_handle:
            handler.on_modified(event)
            mock_handle.assert_called_once_with(event)

    def test_on_created_calls_handle(self, tmp_path: Path) -> None:
        """Should call _handle on created event."""
        config_path = tmp_path / "config.yaml"
        watcher = ConfigWatcher(
            config_path=str(config_path),
            enabled=False,
        )
        handler = _ConfigEventHandler(watcher)

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(config_path)

        with patch.object(handler, "_handle") as mock_handle:
            handler.on_created(event)
            mock_handle.assert_called_once_with(event)


class TestConfigWatcherConstants:
    """Tests for module constants."""

    def test_default_debounce_ms(self) -> None:
        """Should have correct default debounce value."""
        assert DEFAULT_DEBOUNCE_MS == 500

    def test_hot_reload_keys(self) -> None:
        """Should contain expected hot-reload keys."""
        assert "providers" in HOT_RELOAD_KEYS
        assert "memory" in HOT_RELOAD_KEYS
        assert "skills" in HOT_RELOAD_KEYS

    def test_restart_required_keys(self) -> None:
        """Should contain expected restart-required keys."""
        assert "gateway.host" in RESTART_REQUIRED_KEYS
        assert "gateway.port" in RESTART_REQUIRED_KEYS
