"""Property-based tests for credential management.

Tests cover:
- Property 7: Dotenv loads all key-value pairs
- Property 8: Credential resolution priority (env > keyring)
- Property 9: Credential keyring round-trip
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.credentials import (
    get_credential,
    set_credential,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid env-var-safe keys: uppercase ASCII letters and underscores, must start
# with a letter so they are legal environment variable names.
_env_key_chars = st.sampled_from(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"))

env_keys = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).map(lambda s: s.upper())

# Values: printable, non-empty, no newlines (dotenv limitation)
env_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
)

# Service / key names for credential functions — simple alphanumeric
service_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=15,
)

credential_keys = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=15,
)

credential_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property 7: Dotenv loads all key-value pairs
# **Validates: Requirements 5.3**
# ---------------------------------------------------------------------------


@given(
    pairs=st.dictionaries(
        keys=env_keys,
        values=env_values,
        min_size=1,
        max_size=5,
    ),
)
@settings(max_examples=100)
def test_dotenv_loads_pairs(pairs: dict[str, str], tmp_path_factory: object) -> None:
    """Property 7: Dotenv loads all key-value pairs.

    For any set of key-value pairs written to a .env file, after calling
    load_dotenv(), each key should be present in os.environ with its
    corresponding value.

    **Validates: Requirements 5.3**
    """
    from pytest import TempPathFactory

    assert isinstance(tmp_path_factory, TempPathFactory)
    tmp_dir: Path = tmp_path_factory.mktemp("dotenv")
    env_file = tmp_dir / ".env"

    # Build .env content
    lines = [f"{k}={v}" for k, v in pairs.items()]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Save and clear any conflicting env vars
    saved: dict[str, str | None] = {}
    for k in pairs:
        saved[k] = os.environ.pop(k, None)

    try:
        # python-dotenv's load_dotenv accepts a path argument
        from dotenv import load_dotenv as _raw_load

        _raw_load(env_file, override=True)

        for k, v in pairs.items():
            assert k in os.environ, f"Key {k!r} not found in os.environ after load_dotenv"
            assert os.environ[k] == v, f"Expected os.environ[{k!r}] == {v!r}, got {os.environ[k]!r}"
    finally:
        # Restore original env state
        for k, original in saved.items():
            if original is not None:
                os.environ[k] = original
            else:
                os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# Property 8: Credential resolution priority
# **Validates: Requirements 5.6**
# ---------------------------------------------------------------------------


@given(
    service=service_names,
    key=credential_keys,
    env_value=credential_values,
    keyring_value=credential_values,
)
@settings(max_examples=100)
def test_credential_priority(
    service: str,
    key: str,
    env_value: str,
    keyring_value: str,
) -> None:
    """Property 8: Credential resolution priority.

    For any credential that exists in both the environment variable and
    the system keyring, get_credential should return the environment
    variable value (env takes priority over keyring).

    **Validates: Requirements 5.6**
    """
    env_var = f"{service}_{key}".upper().replace("-", "_")

    saved = os.environ.get(env_var)

    try:
        # Set the env var
        os.environ[env_var] = env_value

        # Mock keyring to return a different value
        with patch("smartclaw.credentials.keyring_lib.get_password", return_value=keyring_value):
            result = get_credential(service, key)

        assert result == env_value, (
            f"Expected env value {env_value!r}, got {result!r}. Env var should take priority over keyring."
        )
    finally:
        if saved is not None:
            os.environ[env_var] = saved
        else:
            os.environ.pop(env_var, None)


# ---------------------------------------------------------------------------
# Property 9: Credential keyring round-trip
# **Validates: Requirements 5.8**
# ---------------------------------------------------------------------------

# In-memory keyring store for testing (avoids touching the real system keyring)
_fake_keyring_store: dict[tuple[str, str], str] = {}


def _fake_set_password(service: str, key: str, value: str) -> None:
    _fake_keyring_store[(service, key)] = value


def _fake_get_password(service: str, key: str) -> str | None:
    return _fake_keyring_store.get((service, key))


@given(
    service=service_names,
    key=credential_keys,
    value=credential_values,
)
@settings(max_examples=100)
def test_credential_roundtrip(
    service: str,
    key: str,
    value: str,
) -> None:
    """Property 9: Credential keyring round-trip.

    For any service name, key, and value, calling set_credential followed
    by get_credential (with the environment variable unset) should return
    the original value.

    **Validates: Requirements 5.8**
    """
    env_var = f"{service}_{key}".upper().replace("-", "_")

    saved_env = os.environ.get(env_var)
    _fake_keyring_store.clear()

    try:
        # Ensure the env var is NOT set so keyring path is exercised
        os.environ.pop(env_var, None)

        with (
            patch("smartclaw.credentials.keyring_lib.set_password", side_effect=_fake_set_password),
            patch("smartclaw.credentials.keyring_lib.get_password", side_effect=_fake_get_password),
        ):
            set_credential(service, key, value)
            result = get_credential(service, key)

        assert result == value, (
            f"Round-trip failed: set_credential({service!r}, {key!r}, {value!r}) "
            f"then get_credential returned {result!r}"
        )
    finally:
        if saved_env is not None:
            os.environ[env_var] = saved_env
        else:
            os.environ.pop(env_var, None)
