"""Property-based tests for MCP config models.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from smartclaw.mcp.config import MCPConfig, MCPServerConfig


# ---------------------------------------------------------------------------
# Strategies for invalid inputs
# ---------------------------------------------------------------------------

# Values that cannot be coerced to bool by Pydantic
_non_bool_values = st.one_of(
    st.lists(st.integers(), min_size=1),
    st.dictionaries(st.text(min_size=1), st.integers(), min_size=1),
)

# Values that cannot be coerced to list[str]
_non_list_values = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

# Values that cannot be coerced to dict[str, str]
_non_dict_values = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=1, max_size=5),
)


# ---------------------------------------------------------------------------
# Property 12: Pydantic validation rejects invalid types
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 12: Pydantic validation rejects invalid types
@given(bad_enabled=_non_bool_values)
@settings(max_examples=100)
def test_mcp_server_config_rejects_invalid_enabled(bad_enabled: object) -> None:
    """For any non-bool-coercible value for 'enabled', MCPServerConfig
    construction shall raise ValidationError.

    **Validates: Requirements 7.5**
    """
    try:
        MCPServerConfig(enabled=bad_enabled)  # type: ignore[arg-type]
        # If Pydantic coerced it, that's acceptable — but lists/dicts should fail
        assert False, f"Expected ValidationError for enabled={bad_enabled!r}"
    except ValidationError:
        pass  # Expected


# Feature: smartclaw-mcp-protocol, Property 12: Pydantic validation rejects invalid types
@given(bad_args=_non_list_values)
@settings(max_examples=100)
def test_mcp_server_config_rejects_invalid_args(bad_args: object) -> None:
    """For any non-list value for 'args', MCPServerConfig construction
    shall raise ValidationError.

    **Validates: Requirements 7.5**
    """
    try:
        MCPServerConfig(args=bad_args)  # type: ignore[arg-type]
        assert False, f"Expected ValidationError for args={bad_args!r}"
    except ValidationError:
        pass  # Expected


# Feature: smartclaw-mcp-protocol, Property 12: Pydantic validation rejects invalid types
@given(bad_env=_non_dict_values)
@settings(max_examples=100)
def test_mcp_server_config_rejects_invalid_env(bad_env: object) -> None:
    """For any non-dict value for 'env', MCPServerConfig construction
    shall raise ValidationError.

    **Validates: Requirements 7.5**
    """
    try:
        MCPServerConfig(env=bad_env)  # type: ignore[arg-type]
        assert False, f"Expected ValidationError for env={bad_env!r}"
    except ValidationError:
        pass  # Expected


# Feature: smartclaw-mcp-protocol, Property 12: Pydantic validation rejects invalid types
@given(bad_servers=_non_dict_values)
@settings(max_examples=100)
def test_mcp_config_rejects_invalid_servers(bad_servers: object) -> None:
    """For any non-dict value for 'servers', MCPConfig construction
    shall raise ValidationError.

    **Validates: Requirements 7.5**
    """
    try:
        MCPConfig(servers=bad_servers)  # type: ignore[arg-type]
        assert False, f"Expected ValidationError for servers={bad_servers!r}"
    except ValidationError:
        pass  # Expected
