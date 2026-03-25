"""Property-based tests for ModelConfig and parse_model_ref.

Feature: smartclaw-llm-agent-core
"""

import os

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.config.settings import SmartClawSettings
from smartclaw.providers.config import parse_model_ref

# Strategy: non-empty strings without "/"
_no_slash_text = st.text(
    alphabet=st.characters(blacklist_characters="/"),
    min_size=1,
).filter(lambda s: s.strip() == s and len(s) > 0)


# Feature: smartclaw-llm-agent-core, Property 3: Model reference round-trip parsing
class TestModelRefRoundTrip:
    """**Validates: Requirements 2.1**"""

    @given(provider=_no_slash_text, model=_no_slash_text)
    @settings(max_examples=100)
    def test_round_trip(self, provider: str, model: str) -> None:
        """For any non-empty provider/model strings without '/',
        parse_model_ref(f'{provider}/{model}') returns (provider, model) exactly."""
        ref = f"{provider}/{model}"
        parsed_provider, parsed_model = parse_model_ref(ref)
        assert parsed_provider == provider
        assert parsed_model == model


# Strategy for env-safe text (printable ASCII, no null bytes or surrogates)
_env_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
        max_codepoint=127,
    ),
    min_size=1,
    max_size=20,
)


# Feature: smartclaw-llm-agent-core, Property 4: Environment variable overrides model configuration
class TestEnvVarOverrides:
    """**Validates: Requirements 2.4**"""

    @given(
        provider_part=_env_safe_text,
        model_part=_env_safe_text,
    )
    @settings(max_examples=100)
    def test_env_override_primary(self, provider_part: str, model_part: str) -> None:
        """Setting SMARTCLAW_MODEL__PRIMARY overrides model.primary."""
        primary = f"{provider_part}/{model_part}"
        env_key = "SMARTCLAW_MODEL__PRIMARY"
        old = os.environ.get(env_key)
        try:
            os.environ[env_key] = primary
            settings_obj = SmartClawSettings()
            assert settings_obj.model.primary == primary
        finally:
            if old is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old

    @given(temperature=st.floats(min_value=0.0, max_value=2.0, allow_nan=False))
    @settings(max_examples=100)
    def test_env_override_temperature(self, temperature: float) -> None:
        """Setting SMARTCLAW_MODEL__TEMPERATURE overrides model.temperature."""
        env_key = "SMARTCLAW_MODEL__TEMPERATURE"
        old = os.environ.get(env_key)
        try:
            os.environ[env_key] = str(temperature)
            settings_obj = SmartClawSettings()
            assert abs(settings_obj.model.temperature - temperature) < 1e-6
        finally:
            if old is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old

    @given(max_tokens=st.integers(min_value=1, max_value=131072))
    @settings(max_examples=100)
    def test_env_override_max_tokens(self, max_tokens: int) -> None:
        """Setting SMARTCLAW_MODEL__MAX_TOKENS overrides model.max_tokens."""
        env_key = "SMARTCLAW_MODEL__MAX_TOKENS"
        old = os.environ.get(env_key)
        try:
            os.environ[env_key] = str(max_tokens)
            settings_obj = SmartClawSettings()
            assert settings_obj.model.max_tokens == max_tokens
        finally:
            if old is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old
