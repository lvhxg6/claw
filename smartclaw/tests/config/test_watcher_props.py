"""Property tests for ConfigWatcher.

Tests the correctness properties of ConfigWatcher using hypothesis.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
import tempfile

from hypothesis import given, settings, strategies as st, assume, HealthCheck

from smartclaw.config.watcher import (
    HOT_RELOAD_KEYS,
    RESTART_REQUIRED_KEYS,
    ConfigWatcher,
)


# Strategy for generating valid configuration values
config_value_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=0, max_value=10000),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    st.text(min_size=0, max_size=50),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.one_of(st.booleans(), st.integers(), st.text(max_size=20)),
        max_size=5,
    ),
)


class TestProperty13ConfigHotReloadScope:
    """Property 13: 配置热更新范围.

    For any config.yaml change, providers, memory, skills, logging.level
    should support hot-reload; gateway.host, gateway.port changes should
    be marked as requiring restart.

    Validates: Requirements 4.6, 4.7
    """

    @settings(max_examples=100)
    @given(
        old_value=config_value_strategy,
        new_value=config_value_strategy,
    )
    def test_providers_changes_are_hot_reloadable(
        self, old_value: Any, new_value: Any
    ) -> None:
        """Changes to 'providers' should be hot-reloadable."""
        assume(old_value != new_value)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"providers": old_value}
        new_config = {"providers": new_value}

        changed, restart = watcher._diff_config(old_config, new_config)

        assert "providers" in changed
        assert "providers" not in restart

    @settings(max_examples=100)
    @given(
        old_value=config_value_strategy,
        new_value=config_value_strategy,
    )
    def test_memory_changes_are_hot_reloadable(
        self, old_value: Any, new_value: Any
    ) -> None:
        """Changes to 'memory' should be hot-reloadable."""
        assume(old_value != new_value)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"memory": old_value}
        new_config = {"memory": new_value}

        changed, restart = watcher._diff_config(old_config, new_config)

        assert "memory" in changed
        assert "memory" not in restart

    @settings(max_examples=100)
    @given(
        old_value=config_value_strategy,
        new_value=config_value_strategy,
    )
    def test_skills_changes_are_hot_reloadable(
        self, old_value: Any, new_value: Any
    ) -> None:
        """Changes to 'skills' should be hot-reloadable."""
        assume(old_value != new_value)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"skills": old_value}
        new_config = {"skills": new_value}

        changed, restart = watcher._diff_config(old_config, new_config)

        assert "skills" in changed
        assert "skills" not in restart

    @settings(max_examples=100)
    @given(
        old_value=config_value_strategy,
        new_value=config_value_strategy,
    )
    def test_logging_changes_are_hot_reloadable(
        self, old_value: Any, new_value: Any
    ) -> None:
        """Changes to 'logging' should be hot-reloadable."""
        assume(old_value != new_value)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"logging": old_value}
        new_config = {"logging": new_value}

        changed, restart = watcher._diff_config(old_config, new_config)

        assert "logging" in changed
        assert "logging" not in restart

    @settings(max_examples=100)
    @given(
        old_port=st.integers(min_value=1, max_value=65535),
        new_port=st.integers(min_value=1, max_value=65535),
    )
    def test_gateway_port_changes_require_restart(
        self, old_port: int, new_port: int
    ) -> None:
        """Changes to 'gateway.port' should require restart."""
        assume(old_port != new_port)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"gateway": {"port": old_port}}
        new_config = {"gateway": {"port": new_port}}

        changed, restart = watcher._diff_config(old_config, new_config)

        # gateway or gateway.port should be in restart set
        assert "gateway" in restart or "gateway.port" in restart

    @settings(max_examples=100)
    @given(
        old_host=st.text(min_size=1, max_size=50),
        new_host=st.text(min_size=1, max_size=50),
    )
    def test_gateway_host_changes_require_restart(
        self, old_host: str, new_host: str
    ) -> None:
        """Changes to 'gateway.host' should require restart."""
        assume(old_host != new_host)

        watcher = ConfigWatcher(enabled=False)
        old_config = {"gateway": {"host": old_host}}
        new_config = {"gateway": {"host": new_host}}

        changed, restart = watcher._diff_config(old_config, new_config)

        # gateway or gateway.host should be in restart set
        assert "gateway" in restart or "gateway.host" in restart


class TestConfigValidationProperties:
    """Property tests for configuration validation."""

    @settings(max_examples=100)
    @given(chunk_tokens=st.integers(min_value=1, max_value=10000))
    def test_valid_chunk_tokens_accepted(self, chunk_tokens: int) -> None:
        """Valid chunk_tokens values should be accepted."""
        watcher = ConfigWatcher(enabled=False)
        config = {"memory": {"chunk_tokens": chunk_tokens}}
        errors = watcher._validate_config(config)
        assert not any("chunk_tokens" in e for e in errors)

    @settings(max_examples=100)
    @given(chunk_tokens=st.integers(max_value=0))
    def test_invalid_chunk_tokens_rejected(self, chunk_tokens: int) -> None:
        """Invalid chunk_tokens values should be rejected."""
        watcher = ConfigWatcher(enabled=False)
        config = {"memory": {"chunk_tokens": chunk_tokens}}
        errors = watcher._validate_config(config)
        assert any("chunk_tokens" in e for e in errors)

    @settings(max_examples=100)
    @given(weight=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    def test_valid_vector_weight_accepted(self, weight: float) -> None:
        """Valid vector_weight values should be accepted."""
        watcher = ConfigWatcher(enabled=False)
        config = {"memory": {"vector_weight": weight}}
        errors = watcher._validate_config(config)
        assert not any("vector_weight" in e for e in errors)

    @settings(max_examples=100)
    @given(
        weight=st.one_of(
            st.floats(max_value=-0.01, allow_nan=False),
            st.floats(min_value=1.01, allow_nan=False),
        )
    )
    def test_invalid_vector_weight_rejected(self, weight: float) -> None:
        """Invalid vector_weight values should be rejected."""
        assume(not (0 <= weight <= 1))

        watcher = ConfigWatcher(enabled=False)
        config = {"memory": {"vector_weight": weight}}
        errors = watcher._validate_config(config)
        assert any("vector_weight" in e for e in errors)

    @settings(max_examples=100)
    @given(port=st.integers(min_value=1, max_value=65535))
    def test_valid_port_accepted(self, port: int) -> None:
        """Valid port values should be accepted."""
        watcher = ConfigWatcher(enabled=False)
        config = {"gateway": {"port": port}}
        errors = watcher._validate_config(config)
        assert not any("port" in e for e in errors)

    @settings(max_examples=100)
    @given(
        port=st.one_of(
            st.integers(max_value=0),
            st.integers(min_value=65536),
        )
    )
    def test_invalid_port_rejected(self, port: int) -> None:
        """Invalid port values should be rejected."""
        watcher = ConfigWatcher(enabled=False)
        config = {"gateway": {"port": port}}
        errors = watcher._validate_config(config)
        assert any("port" in e for e in errors)

    @settings(max_examples=100)
    @given(level=st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]))
    def test_valid_log_level_accepted(self, level: str) -> None:
        """Valid log levels should be accepted."""
        watcher = ConfigWatcher(enabled=False)
        config = {"logging": {"level": level}}
        errors = watcher._validate_config(config)
        assert not any("level" in e for e in errors)


class TestConfigDiffProperties:
    """Property tests for configuration diff computation."""

    @settings(max_examples=100)
    @given(
        config=st.dictionaries(
            keys=st.sampled_from(["providers", "memory", "skills", "logging", "gateway", "other"]),
            values=config_value_strategy,
            min_size=1,
            max_size=5,
        )
    )
    def test_identical_configs_have_no_diff(self, config: dict[str, Any]) -> None:
        """Identical configurations should have no diff."""
        watcher = ConfigWatcher(enabled=False)
        changed, restart = watcher._diff_config(config, config.copy())
        assert changed == set()
        assert restart == set()

    @settings(max_examples=100)
    @given(
        key=st.text(min_size=1, max_size=20).filter(
            lambda k: k not in HOT_RELOAD_KEYS
            and k not in RESTART_REQUIRED_KEYS
            and not k.startswith("gateway")
        ),
        value=config_value_strategy,
    )
    def test_unknown_keys_are_hot_reloadable(self, key: str, value: Any) -> None:
        """Unknown configuration keys should be treated as hot-reloadable."""
        watcher = ConfigWatcher(enabled=False)
        old_config: dict[str, Any] = {}
        new_config = {key: value}

        changed, restart = watcher._diff_config(old_config, new_config)

        # Unknown keys should be in changed, not restart
        if key in changed or key in restart:
            assert key not in restart or key in changed


class TestConfigReloadDebounceProperties:
    """Property tests for reload debounce behavior."""

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        num_events=st.integers(min_value=2, max_value=10),
        debounce_ms=st.integers(min_value=20, max_value=100),
    )
    def test_multiple_changes_coalesce(
        self, num_events: int, debounce_ms: int
    ) -> None:
        """Multiple config changes within debounce window should coalesce."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"
            config_path.write_text(yaml.dump({"providers": {}}))

            callback = MagicMock()
            watcher = ConfigWatcher(
                config_path=str(config_path),
                debounce_ms=debounce_ms,
                on_reload=callback,
                enabled=False,
            )
            watcher._current_config = {}

            # Schedule multiple reloads rapidly
            for _ in range(num_events):
                watcher._schedule_reload()

            # Wait for debounce
            time.sleep((debounce_ms + 50) / 1000.0)

            # Should only call once
            assert callback.call_count == 1


class TestConfigErrorRecoveryProperties:
    """Property tests for error recovery behavior."""

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        old_config=st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.text(max_size=20),
            min_size=1,
            max_size=3,
        ),
    )
    def test_invalid_yaml_preserves_old_config(
        self, old_config: dict[str, Any]
    ) -> None:
        """Invalid YAML should preserve the old configuration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"
            config_path.write_text("invalid: yaml: content: [")

            watcher = ConfigWatcher(
                config_path=str(config_path),
                enabled=False,
            )
            watcher._current_config = old_config.copy()
            watcher._last_valid_config = old_config.copy()

            watcher._do_reload()

            # Old config should be preserved
            assert watcher.current_config == old_config

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        old_config=st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.text(max_size=20),
            min_size=1,
            max_size=3,
        ),
    )
    def test_validation_error_preserves_old_config(
        self, old_config: dict[str, Any]
    ) -> None:
        """Validation errors should preserve the old configuration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"
            # Write config with invalid values
            config_path.write_text(yaml.dump({"memory": {"chunk_tokens": -999}}))

            watcher = ConfigWatcher(
                config_path=str(config_path),
                enabled=False,
            )
            watcher._current_config = old_config.copy()
            watcher._last_valid_config = old_config.copy()

            watcher._do_reload()

            # Old config should be preserved
            assert watcher.current_config == old_config

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        old_config=st.fixed_dictionaries({
            "providers": st.dictionaries(
                keys=st.text(min_size=1, max_size=5),
                values=st.text(max_size=10),
                max_size=2,
            )
        }),
    )
    def test_callback_error_rollback(
        self, old_config: dict[str, Any]
    ) -> None:
        """Callback errors should rollback to old configuration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yaml"
            config_path.write_text(yaml.dump({"providers": {"new": "value"}}))

            callback = MagicMock(side_effect=Exception("Callback error"))
            watcher = ConfigWatcher(
                config_path=str(config_path),
                on_reload=callback,
                enabled=False,
            )
            watcher._current_config = old_config.copy()

            watcher._do_reload()

            # Should rollback to old config
            assert watcher.current_config == old_config
