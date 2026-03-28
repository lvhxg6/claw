"""Credential management — dotenv + keyring resolution.

Provides a layered credential resolution strategy:
    1. Environment variables: ``{SERVICE}_{KEY}`` (uppercase, underscores)
    2. System keyring: via ``keyring.get_password(service, key)``

Functions:
    load_dotenv — load ``.env`` file into process environment
    get_credential — resolve a credential by service + key
    set_credential — store a credential in the system keyring
"""

from __future__ import annotations

import os

import keyring as keyring_lib
from dotenv import load_dotenv as _dotenv_load


class CredentialNotFoundError(Exception):
    """Raised when a credential cannot be resolved from any source."""

    def __init__(self, service: str, key: str) -> None:
        self.service = service
        self.key = key
        super().__init__(f"Credential not found: service={service!r}, key={key!r}")


def load_dotenv() -> None:
    """Load environment variables from a ``.env`` file.

    Uses ``python-dotenv`` to read the ``.env`` file at the current
    working directory (or its parents).  Silently continues if the
    file does not exist.
    """
    # Override inherited shell placeholders or stale IDE-injected values.
    # In local development the project .env should win.
    _dotenv_load(override=True)


def get_credential(service: str, key: str) -> str:
    """Resolve a credential value by *service* and *key*.

    Resolution priority:
        1. Environment variable ``{SERVICE}_{KEY}`` (uppercase, underscores)
        2. System keyring via ``keyring.get_password(service, key)``

    Args:
        service: Logical service name (e.g. ``"openai"``).
        key: Credential key within the service (e.g. ``"api_key"``).

    Returns:
        The credential value as a string.

    Raises:
        CredentialNotFoundError: If the credential is not found in any source.
    """
    env_var = f"{service}_{key}".upper().replace("-", "_")
    env_value = os.environ.get(env_var)
    if env_value is not None:
        return env_value

    kr_value = keyring_lib.get_password(service, key)
    if kr_value is not None:
        return kr_value

    raise CredentialNotFoundError(service, key)


def set_credential(service: str, key: str, value: str) -> None:
    """Store a credential in the system keyring.

    Args:
        service: Logical service name.
        key: Credential key within the service.
        value: The secret value to store.
    """
    keyring_lib.set_password(service, key, value)
