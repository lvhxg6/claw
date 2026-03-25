"""Unit tests for the SmartClaw entry point initialization sequence.

Verifies:
- Initialization order: dotenv → config → logging
- Startup log message is emitted
- Error handling for missing config, validation errors, etc.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from smartclaw.config.settings import LoggingSettings, SmartClawSettings
from smartclaw.main import _init, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_config(path: Path) -> Path:
    """Write a minimal valid YAML config and return its path."""
    cfg = path / "config.yaml"
    cfg.write_text(
        yaml.dump({"logging": {"level": "INFO", "format": "console"}}),
        encoding="utf-8",
    )
    return cfg


# ---------------------------------------------------------------------------
# Test: initialization order
# ---------------------------------------------------------------------------


class TestInitOrder:
    """Verify that _init() calls subsystems in the correct order."""

    def test_init_calls_dotenv_before_config_before_logging(self, tmp_path: Path) -> None:
        """dotenv must be called before load_config, which must be called before setup_logging."""
        call_order: list[str] = []

        fake_settings = SmartClawSettings()

        def fake_load_dotenv() -> None:
            call_order.append("load_dotenv")

        def fake_load_config(config_path: object = None) -> SmartClawSettings:
            call_order.append("load_config")
            return fake_settings

        def fake_setup_logging(settings: LoggingSettings) -> None:
            call_order.append("setup_logging")

        with (
            patch("smartclaw.main.load_dotenv", side_effect=fake_load_dotenv),
            patch("smartclaw.main.load_config", side_effect=fake_load_config),
            patch("smartclaw.main.setup_logging", side_effect=fake_setup_logging),
        ):
            result = _init()

        assert call_order == ["load_dotenv", "load_config", "setup_logging"]
        assert result is fake_settings

    def test_setup_logging_receives_logging_settings(self) -> None:
        """setup_logging must be called with settings.logging."""
        fake_settings = SmartClawSettings()
        mock_setup = MagicMock()

        with (
            patch("smartclaw.main.load_dotenv"),
            patch("smartclaw.main.load_config", return_value=fake_settings),
            patch("smartclaw.main.setup_logging", mock_setup),
        ):
            _init()

        mock_setup.assert_called_once_with(fake_settings.logging)


# ---------------------------------------------------------------------------
# Test: startup log message
# ---------------------------------------------------------------------------


class TestStartupMessage:
    """Verify that main() emits a startup log message."""

    def test_startup_message_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """After successful init, a 'SmartClaw started' message should appear."""
        fake_settings = SmartClawSettings()

        with (
            patch("smartclaw.main.load_dotenv"),
            patch("smartclaw.main.load_config", return_value=fake_settings),
            patch("smartclaw.main.setup_logging"),
            caplog.at_level(logging.INFO),
        ):
            # We also need to patch get_logger to return a logger that writes
            # to the standard logging so caplog can capture it.
            mock_logger = MagicMock()
            with patch("smartclaw.main.get_logger", return_value=mock_logger):
                main()

        mock_logger.info.assert_called_once()
        args, kwargs = mock_logger.info.call_args
        assert "SmartClaw started" in args[0]


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify graceful error handling in main()."""

    def test_file_not_found_exits_with_code_1(self) -> None:
        """main() should sys.exit(1) when config file is missing."""
        with (
            patch("smartclaw.main.load_dotenv"),
            patch("smartclaw.main.load_config", side_effect=FileNotFoundError("config/config.yaml")),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1

    def test_validation_error_exits_with_code_1(self) -> None:
        """main() should sys.exit(1) on pydantic ValidationError."""
        from pydantic import ValidationError

        with (
            patch("smartclaw.main.load_dotenv"),
            patch(
                "smartclaw.main.load_config",
                side_effect=ValidationError.from_exception_data(
                    title="SmartClawSettings",
                    line_errors=[],
                ),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1

    def test_unexpected_error_exits_with_code_1(self) -> None:
        """main() should sys.exit(1) on any unexpected exception."""
        with (
            patch("smartclaw.main.load_dotenv"),
            patch("smartclaw.main.load_config", side_effect=RuntimeError("boom")),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1
