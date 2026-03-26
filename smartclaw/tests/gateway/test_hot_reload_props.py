# Feature: smartclaw-p2a-production-services, Property 6: 有效配置变更触发热重载
# Feature: smartclaw-p2a-production-services, Property 7: 无效配置保留当前设置
"""Property tests for HotReloader.

**Validates: Requirements 7.2, 7.3**
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.gateway.hot_reload import HotReloader
from smartclaw.config.settings import SmartClawSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(initial_settings: SmartClawSettings | None = None) -> MagicMock:
    """Return a mock FastAPI app with app.state.settings."""
    app = MagicMock()
    app.state = MagicMock()
    app.state.settings = initial_settings or SmartClawSettings()
    return app


def _write_yaml(path: str, data: dict) -> None:
    """Write a dict as YAML to path and bump mtime by at least 0.01s."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    # Ensure mtime is strictly newer than the previous write
    current = os.path.getmtime(path)
    os.utime(path, (current + 1.0, current + 1.0))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid gateway port values
_valid_port = st.integers(min_value=1024, max_value=65535)

# Valid log levels
_valid_log_level = st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

# Valid gateway host strings
_valid_host = st.sampled_from(["0.0.0.0", "127.0.0.1", "localhost"])


@st.composite
def valid_config_dict(draw: Any) -> dict:
    """Generate a valid SmartClaw config dict."""
    port = draw(_valid_port)
    level = draw(_valid_log_level)
    host = draw(_valid_host)
    return {
        "gateway": {
            "enabled": False,
            "host": host,
            "port": port,
        },
        "logging": {
            "level": level,
        },
    }


@st.composite
def invalid_config_content(draw: Any) -> str:
    """Generate invalid YAML or Pydantic-invalid config content.

    Uses a fixed set of reliably-invalid inputs to avoid Pydantic coercion
    edge cases (e.g. '+0' is coerced to int 0).
    """
    # All entries here are guaranteed to either be syntactically invalid YAML
    # or produce a Pydantic ValidationError (non-coercible to the target type).
    return draw(st.sampled_from([
        # --- Invalid YAML syntax ---
        "gateway: {port: [unclosed",
        ": : : invalid yaml :::",
        "gateway:\n  port:\n    - nested: {broken",
        # --- Valid YAML but Pydantic rejects: shutdown_timeout must be int ---
        "gateway:\n  shutdown_timeout: not_an_integer\n",
        "gateway:\n  shutdown_timeout: abc\n",
        "gateway:\n  shutdown_timeout: hello_world\n",
        "gateway:\n  shutdown_timeout: 1.5\n",
        "gateway:\n  shutdown_timeout: 2.7\n",
        # --- Valid YAML but Pydantic rejects: reload_interval must be int ---
        "gateway:\n  reload_interval: not_an_integer\n",
        "gateway:\n  reload_interval: abc\n",
        "gateway:\n  reload_interval: 3.14\n",
    ]))


# ---------------------------------------------------------------------------
# Property 6: 有效配置变更触发热重载
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(valid_config_dict())
def test_valid_config_change_triggers_reload(config_data: dict) -> None:
    """For any valid YAML config change (modify mtime), HotReloader detects change
    and updates app.state.settings.

    **Validates: Requirements 7.2**
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump({}, f)
        tmp_path = f.name

    try:
        app = _make_app()
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        # Seed the initial mtime
        reloader._last_mtime = os.path.getmtime(tmp_path)

        # Write new valid config and bump mtime
        _write_yaml(tmp_path, config_data)

        # Run _reload() directly (no need to spin up the full poll loop)
        asyncio.get_event_loop().run_until_complete(reloader._reload())

        # Settings should have been updated
        new_settings = app.state.settings
        assert isinstance(new_settings, SmartClawSettings)

        # Verify specific fields if present in config_data
        if "gateway" in config_data and "port" in config_data["gateway"]:
            assert new_settings.gateway.port == config_data["gateway"]["port"]
        if "gateway" in config_data and "host" in config_data["gateway"]:
            assert new_settings.gateway.host == config_data["gateway"]["host"]
        if "logging" in config_data and "level" in config_data["logging"]:
            assert new_settings.logging.level == config_data["logging"]["level"]
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Property 7: 无效配置保留当前设置
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(invalid_config_content())
def test_invalid_config_keeps_current_settings(bad_content: str) -> None:
    """For any invalid YAML or Pydantic validation failure, HotReloader keeps
    current config unchanged.

    **Validates: Requirements 7.3**
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(bad_content)
        tmp_path = f.name

    try:
        original_settings = SmartClawSettings()
        app = _make_app(original_settings)
        reloader = HotReloader(config_path=tmp_path, app=app, interval=0.05)

        # Run _reload() directly
        asyncio.get_event_loop().run_until_complete(reloader._reload())

        # Settings must remain the original object (unchanged)
        assert app.state.settings is original_settings
    finally:
        os.unlink(tmp_path)
