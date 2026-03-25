"""Property-based tests for environment variable merge precedence.

Uses hypothesis with @settings(max_examples=100).
Tests Property 10.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.mcp.config import MCPServerConfig
from smartclaw.mcp.manager import _merge_env


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_env_key = st.from_regex(r"SMARTCLAW_TEST_[A-Z]{1,8}", fullmatch=True)
_env_val = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_env_mapping = st.dictionaries(_env_key, _env_val, min_size=0, max_size=5)


# ---------------------------------------------------------------------------
# Property 10: Environment variable merge precedence
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 10: Environment variable merge precedence
@given(
    parent_env=_env_mapping,
    file_env=_env_mapping,
    config_env=_env_mapping,
)
@settings(max_examples=100)
def test_env_merge_precedence(
    parent_env: dict[str, str],
    file_env: dict[str, str],
    config_env: dict[str, str],
) -> None:
    """The resulting subprocess environment reflects precedence:
    parent env < env_file < env mapping.

    **Validates: Requirements 2.4, 2.5**
    """
    # Write env_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        for k, v in file_env.items():
            f.write(f"{k}={v}\n")
        env_file_path = f.name

    try:
        config = MCPServerConfig(
            command="test",
            env=config_env,
            env_file=env_file_path,
        )

        # Patch os.environ to control parent env
        with patch.dict(os.environ, parent_env, clear=False):
            result = _merge_env(config)

        # Check precedence: config_env > file_env > parent_env
        all_keys = set(parent_env.keys()) | set(file_env.keys()) | set(config_env.keys())
        for key in all_keys:
            if key in config_env:
                assert result[key] == config_env[key], (
                    f"Key {key}: expected config_env value {config_env[key]!r}, got {result[key]!r}"
                )
            elif key in file_env:
                assert result[key] == file_env[key], (
                    f"Key {key}: expected file_env value {file_env[key]!r}, got {result[key]!r}"
                )
            elif key in parent_env:
                assert result[key] == parent_env[key], (
                    f"Key {key}: expected parent_env value {parent_env[key]!r}, got {result[key]!r}"
                )
    finally:
        os.unlink(env_file_path)
