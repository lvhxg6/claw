"""Unit tests for HotReloader.

Requirements: 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from smartclaw.config.settings import SmartClawSettings
from smartclaw.gateway.hot_reload import HotReloader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(initial_settings: SmartClawSettings | None = None) -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    app.state.settings = initial_settings or SmartClawSettings()
    return app


def _write_yaml(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    current = os.path.getmtime(path)
    os.utime(path, (current + 1.0, current + 1.0))


# ---------------------------------------------------------------------------
# Test: mtime change detection
# ---------------------------------------------------------------------------


def test_mtime_change_detected() -> None:
    """HotReloader detects when the config file mtime changes (Req 7.1)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({}, f)
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)
        reloader._last_mtime = os.path.getmtime(tmp_path)

        old_mtime = reloader._last_mtime

        # Bump mtime
        current = os.path.getmtime(tmp_path)
        os.utime(tmp_path, (current + 2.0, current + 2.0))

        new_mtime = reloader._get_mtime()
        assert new_mtime != old_mtime
    finally:
        os.unlink(tmp_path)


def test_no_mtime_change_no_reload() -> None:
    """When mtime is unchanged, _reload is not triggered."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({}, f)
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)
        reloader._last_mtime = os.path.getmtime(tmp_path)

        # mtime unchanged → _get_mtime() == _last_mtime
        assert reloader._get_mtime() == reloader._last_mtime
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test: reload success updates app.state.settings
# ---------------------------------------------------------------------------


def test_reload_success_updates_settings() -> None:
    """Successful reload updates app.state.settings with new values (Req 7.2)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({}, f)
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        new_config = {"gateway": {"port": 9999, "host": "127.0.0.1"}}
        _write_yaml(tmp_path, new_config)

        asyncio.get_event_loop().run_until_complete(reloader._reload())

        assert isinstance(app.state.settings, SmartClawSettings)
        assert app.state.settings.gateway.port == 9999
        assert app.state.settings.gateway.host == "127.0.0.1"
    finally:
        os.unlink(tmp_path)


def test_reload_success_replaces_settings_object() -> None:
    """After a successful reload, app.state.settings is a new object (Req 7.2)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({}, f)
        tmp_path = f.name

    try:
        original = SmartClawSettings()
        app = _make_app(original)
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        _write_yaml(tmp_path, {"gateway": {"port": 7777}})
        asyncio.get_event_loop().run_until_complete(reloader._reload())

        # Should be a new settings object
        assert app.state.settings is not original
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test: reload failure keeps old config
# ---------------------------------------------------------------------------


def test_reload_failure_bad_yaml_keeps_old_config() -> None:
    """Invalid YAML keeps current settings unchanged (Req 7.3)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(": : : invalid yaml :::")
        tmp_path = f.name

    try:
        original = SmartClawSettings()
        app = _make_app(original)
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        asyncio.get_event_loop().run_until_complete(reloader._reload())

        # Settings must remain unchanged
        assert app.state.settings is original
    finally:
        os.unlink(tmp_path)


def test_reload_failure_pydantic_validation_keeps_old_config() -> None:
    """Pydantic validation failure keeps current settings unchanged (Req 7.3)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        # shutdown_timeout must be an int; give it a non-coercible string
        yaml.dump({"gateway": {"shutdown_timeout": "not_an_integer"}}, f)
        tmp_path = f.name

    try:
        original = SmartClawSettings()
        app = _make_app(original)
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        asyncio.get_event_loop().run_until_complete(reloader._reload())

        assert app.state.settings is original
    finally:
        os.unlink(tmp_path)


def test_reload_failure_missing_file_keeps_old_config() -> None:
    """Missing config file keeps current settings unchanged (Req 7.3)."""
    original = SmartClawSettings()
    app = _make_app(original)
    reloader = HotReloader(config_path="/nonexistent/path/config.yaml", app=app, interval=0.05)

    asyncio.get_event_loop().run_until_complete(reloader._reload())

    assert app.state.settings is original


# ---------------------------------------------------------------------------
# Test: config.reloaded diagnostic event emitted on success
# ---------------------------------------------------------------------------


def test_reload_success_emits_config_reloaded_event() -> None:
    """Successful reload emits 'config.reloaded' diagnostic event (Req 7.4)."""
    from smartclaw.observability import diagnostic_bus

    received: list[tuple[str, dict]] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        received.append((event_type, payload))

    diagnostic_bus.on("config.reloaded", subscriber)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({"gateway": {"port": 8888}}, f)
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        asyncio.get_event_loop().run_until_complete(reloader._reload())

        assert len(received) == 1
        event_type, payload = received[0]
        assert event_type == "config.reloaded"
        assert payload["success"] is True
        assert "changed_fields" in payload
    finally:
        diagnostic_bus.off("config.reloaded", subscriber)
        os.unlink(tmp_path)


def test_reload_failure_does_not_emit_config_reloaded_event() -> None:
    """Failed reload does NOT emit 'config.reloaded' diagnostic event (Req 7.4)."""
    from smartclaw.observability import diagnostic_bus

    received: list[tuple[str, dict]] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        received.append((event_type, payload))

    diagnostic_bus.on("config.reloaded", subscriber)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(": bad yaml :")
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        asyncio.get_event_loop().run_until_complete(reloader._reload())

        assert len(received) == 0
    finally:
        diagnostic_bus.off("config.reloaded", subscriber)
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Test: start/stop lifecycle
# ---------------------------------------------------------------------------


def test_start_creates_task() -> None:
    """start() creates a background asyncio.Task (lifecycle test)."""

    async def _run() -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump({}, f)
            tmp_path = f.name

        try:
            app = _make_app()
            reloader = HotReloader(config_path=tmp_path, app=app, interval=60.0)

            assert reloader._task is None
            reloader.start()
            assert reloader._task is not None
            assert not reloader._task.done()

            reloader.stop()
            # Give the task a moment to process cancellation
            await asyncio.sleep(0.05)
            assert reloader._task is None or reloader._task.done() or reloader._task.cancelled()
        finally:
            os.unlink(tmp_path)

    asyncio.get_event_loop().run_until_complete(_run())


def test_stop_cancels_task() -> None:
    """stop() cancels the running polling task."""

    async def _run() -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump({}, f)
            tmp_path = f.name

        try:
            app = _make_app()
            reloader = HotReloader(config_path=tmp_path, app=app, interval=60.0)

            reloader.start()
            task = reloader._task
            assert task is not None

            reloader.stop()
            await asyncio.sleep(0.05)

            # Task should be cancelled or done
            assert task.done() or task.cancelled()
        finally:
            os.unlink(tmp_path)

    asyncio.get_event_loop().run_until_complete(_run())


def test_start_idempotent() -> None:
    """Calling start() twice does not create a second task."""

    async def _run() -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump({}, f)
            tmp_path = f.name

        try:
            app = _make_app()
            reloader = HotReloader(config_path=tmp_path, app=app, interval=60.0)

            reloader.start()
            task1 = reloader._task

            reloader.start()  # second call — should reuse existing task
            task2 = reloader._task

            assert task1 is task2

            reloader.stop()
            await asyncio.sleep(0.05)
        finally:
            os.unlink(tmp_path)

    asyncio.get_event_loop().run_until_complete(_run())


def test_stop_without_start_is_safe() -> None:
    """stop() before start() does not raise."""
    app = _make_app()
    reloader = HotReloader(config_path="/tmp/nonexistent.yaml", app=app, interval=5.0)
    reloader.stop()  # should not raise
