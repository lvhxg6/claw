"""Property-based tests for configuration management.

Tests cover:
- Property 1: Configuration round-trip (dump → load equivalence)
- Property 2: Invalid configuration raises ValidationError
- Property 3: Environment variable overrides YAML values
"""

from __future__ import annotations

import os
import textwrap
from typing import Any

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from smartclaw.config.loader import dump_config, load_config
from smartclaw.config.settings import (
    AgentDefaultsSettings,
    CredentialSettings,
    LoggingSettings,
    SmartClawSettings,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

log_levels = st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
log_formats = st.sampled_from(["console", "json"])

# Strategy: file paths that are safe strings (or None)
safe_file_paths = st.one_of(
    st.none(),
    st.text(alphabet=st.characters(whitelist_categories=("L", "N", "P")), min_size=1, max_size=50),
)

# Strategy: workspace paths — non-empty safe strings
workspace_paths = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=80,
)

# Strategy: keyring service names — non-empty safe strings
service_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Strategy: positive integers for token / iteration counts
positive_ints = st.integers(min_value=1, max_value=10_000_000)


@st.composite
def valid_smartclaw_settings(draw: st.DrawFn) -> SmartClawSettings:
    """Generate a valid SmartClawSettings instance."""
    logging_settings = LoggingSettings(
        level=draw(log_levels),
        format=draw(log_formats),
        file=draw(safe_file_paths),
    )
    agent_defaults = AgentDefaultsSettings(
        workspace=draw(workspace_paths),
        max_tokens=draw(positive_ints),
        max_tool_iterations=draw(positive_ints),
    )
    credentials = CredentialSettings(
        keyring_service=draw(service_names),
    )
    return SmartClawSettings(
        logging=logging_settings,
        agent_defaults=agent_defaults,
        credentials=credentials,
    )


# ---------------------------------------------------------------------------
# Property 1: Configuration round-trip
# **Validates: Requirements 4.1, 4.12, 4.13, 4.14**
# ---------------------------------------------------------------------------


@given(original=valid_smartclaw_settings())
@settings(max_examples=100)
def test_config_roundtrip(original: SmartClawSettings, tmp_path_factory: Any) -> None:
    """Property 1: Configuration round-trip.

    For any valid SmartClawSettings, serializing to YAML via dump_config
    and loading back via load_config produces an equivalent object.

    **Validates: Requirements 4.1, 4.12, 4.13, 4.14**
    """
    # Serialize to YAML
    yaml_str = dump_config(original)

    # Write to a temp file
    tmp_path = tmp_path_factory.mktemp("config")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_str, encoding="utf-8")

    # Clear env vars that could interfere
    env_keys_to_clear = [k for k in os.environ if k.startswith("SMARTCLAW_")]
    saved_env: dict[str, str | None] = {}
    for k in env_keys_to_clear:
        saved_env[k] = os.environ.pop(k, None)

    try:
        loaded = load_config(config_file)
        assert loaded.model_dump() == original.model_dump()
    finally:
        # Restore env
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Property 2: Invalid configuration raises ValidationError
# **Validates: Requirements 4.5**
# ---------------------------------------------------------------------------


# Strategy: generate YAML dicts with invalid typed values for known fields
@st.composite
def invalid_config_yaml(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a YAML-compatible dict that violates the Pydantic schema."""
    # Pick which section to corrupt
    section = draw(st.sampled_from(["agent_defaults", "logging", "credentials"]))

    if section == "agent_defaults":
        # max_tokens and max_tool_iterations must be int; supply non-coercible values
        bad_value = draw(st.sampled_from(["not_a_number", [1, 2, 3], {"nested": "dict"}]))
        return {"agent_defaults": {"max_tokens": bad_value}}
    elif section == "logging":
        # level must be str; supply non-str types that Pydantic won't coerce
        bad_value = draw(st.sampled_from([[1, 2], {"a": "b"}]))
        return {"logging": {"level": bad_value}}
    else:
        # keyring_service must be str; supply non-str
        bad_value = draw(st.sampled_from([[1, 2], {"a": "b"}]))
        return {"credentials": {"keyring_service": bad_value}}


@given(bad_data=invalid_config_yaml())
@settings(max_examples=100)
def test_invalid_config_validation(bad_data: dict[str, Any], tmp_path_factory: Any) -> None:
    """Property 2: Invalid configuration raises ValidationError.

    For any YAML configuration containing values that violate the Pydantic
    schema constraints, load_config should raise a ValidationError.

    **Validates: Requirements 4.5**
    """
    tmp_path = tmp_path_factory.mktemp("config")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(bad_data), encoding="utf-8")

    # Clear env vars that could interfere
    env_keys_to_clear = [k for k in os.environ if k.startswith("SMARTCLAW_")]
    saved_env: dict[str, str | None] = {}
    for k in env_keys_to_clear:
        saved_env[k] = os.environ.pop(k, None)

    try:
        try:
            load_config(config_file)
            # If we get here, the invalid data was somehow accepted — fail the test
            raise AssertionError(f"Expected ValidationError for data: {bad_data}")
        except ValidationError:
            pass  # Expected
    finally:
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Property 3: Environment variable overrides configuration values
# **Validates: Requirements 4.10**
# ---------------------------------------------------------------------------


# Strategy: generate a log level for YAML and a different one for env override
@st.composite
def config_with_env_override(draw: st.DrawFn) -> tuple[str, str, int, int]:
    """Generate (yaml_level, env_level, yaml_max_tokens, env_max_tokens).

    Ensures the YAML and env values differ so we can verify the override.
    """
    all_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    yaml_level = draw(st.sampled_from(all_levels))
    env_level = draw(st.sampled_from([lv for lv in all_levels if lv != yaml_level]))

    yaml_tokens = draw(st.integers(min_value=1, max_value=100_000))
    env_tokens = draw(st.integers(min_value=1, max_value=100_000).filter(lambda x: x != yaml_tokens))

    return yaml_level, env_level, yaml_tokens, env_tokens


@given(data=config_with_env_override())
@settings(max_examples=100)
def test_env_override(data: tuple[str, str, int, int], tmp_path_factory: Any) -> None:
    """Property 3: Environment variable overrides configuration values.

    For any configuration field with a corresponding SMARTCLAW_ prefixed
    environment variable set, the loaded SmartClawSettings should reflect
    the environment variable value rather than the YAML file value.

    **Validates: Requirements 4.10**
    """
    yaml_level, env_level, yaml_tokens, env_tokens = data

    yaml_content = textwrap.dedent(f"""\
        logging:
          level: "{yaml_level}"
        agent_defaults:
          max_tokens: {yaml_tokens}
    """)

    tmp_path = tmp_path_factory.mktemp("config")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    # Clear all SMARTCLAW_ env vars first, then set overrides
    env_keys_to_clear = [k for k in os.environ if k.startswith("SMARTCLAW_")]
    saved_env: dict[str, str | None] = {}
    for k in env_keys_to_clear:
        saved_env[k] = os.environ.pop(k, None)

    os.environ["SMARTCLAW_LOGGING__LEVEL"] = env_level
    os.environ["SMARTCLAW_AGENT_DEFAULTS__MAX_TOKENS"] = str(env_tokens)

    try:
        loaded = load_config(config_file)
        assert loaded.logging.level == env_level, (
            f"Expected logging.level={env_level!r} (from env), got {loaded.logging.level!r}"
        )
        assert loaded.agent_defaults.max_tokens == env_tokens, (
            f"Expected max_tokens={env_tokens} (from env), got {loaded.agent_defaults.max_tokens}"
        )
    finally:
        os.environ.pop("SMARTCLAW_LOGGING__LEVEL", None)
        os.environ.pop("SMARTCLAW_AGENT_DEFAULTS__MAX_TOKENS", None)
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
