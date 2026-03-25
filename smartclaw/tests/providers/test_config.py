"""Unit tests for ModelConfig and parse_model_ref."""

import pytest

from smartclaw.config.settings import SmartClawSettings
from smartclaw.providers.config import ModelConfig, parse_model_ref


class TestModelConfigDefaults:
    """Test ModelConfig default values."""

    def test_default_primary(self) -> None:
        cfg = ModelConfig()
        assert cfg.primary == "kimi/moonshot-v1-auto"

    def test_default_fallbacks(self) -> None:
        cfg = ModelConfig()
        assert cfg.fallbacks == ["openai/gpt-4o", "anthropic/claude-sonnet-4-20250514"]

    def test_default_temperature(self) -> None:
        cfg = ModelConfig()
        assert cfg.temperature == 0.0

    def test_default_max_tokens(self) -> None:
        cfg = ModelConfig()
        assert cfg.max_tokens == 32768


class TestModelConfigNested:
    """Test ModelConfig nested in SmartClawSettings."""

    def test_settings_has_model_field(self) -> None:
        settings = SmartClawSettings()
        assert hasattr(settings, "model")
        assert isinstance(settings.model, ModelConfig)

    def test_settings_model_defaults(self) -> None:
        settings = SmartClawSettings()
        assert settings.model.primary == "kimi/moonshot-v1-auto"
        assert settings.model.temperature == 0.0
        assert settings.model.max_tokens == 32768

    def test_settings_model_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMARTCLAW_MODEL__PRIMARY", "openai/gpt-4o")
        settings = SmartClawSettings()
        assert settings.model.primary == "openai/gpt-4o"


class TestParseModelRef:
    """Test parse_model_ref function."""

    def test_valid_ref(self) -> None:
        assert parse_model_ref("openai/gpt-4o") == ("openai", "gpt-4o")

    def test_valid_ref_kimi(self) -> None:
        assert parse_model_ref("kimi/moonshot-v1-auto") == ("kimi", "moonshot-v1-auto")

    def test_valid_ref_with_slashes_in_model(self) -> None:
        assert parse_model_ref("anthropic/claude-sonnet-4-20250514") == (
            "anthropic",
            "claude-sonnet-4-20250514",
        )

    def test_invalid_no_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid model reference"):
            parse_model_ref("openai-gpt4o")

    def test_invalid_empty_provider(self) -> None:
        with pytest.raises(ValueError, match="Invalid model reference"):
            parse_model_ref("/gpt-4o")

    def test_invalid_empty_model(self) -> None:
        with pytest.raises(ValueError, match="Invalid model reference"):
            parse_model_ref("openai/")

    def test_invalid_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid model reference"):
            parse_model_ref("")
