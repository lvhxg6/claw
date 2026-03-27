"""Model configuration and reference parsing for SmartClaw LLM providers."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class ProviderSpec(BaseSettings):
    """Declarative provider specification for config-driven registration.

    Each ProviderSpec defines how to instantiate a LangChain BaseChatModel
    for a given LLM provider, including the import path, API key env var,
    optional base URL, model field name, and extra constructor parameters.

    YAML example:
        providers:
          - name: deepseek
            class_path: "langchain_openai.ChatOpenAI"
            env_key: "DEEPSEEK_API_KEY"
            base_url: "https://api.deepseek.com/v1"
            model_field: "model"
            extra_params:
              timeout: 60
    """

    name: str = Field(description="Provider name (e.g. 'openai', 'deepseek')")
    class_path: str = Field(
        description="Full Python import path of the LangChain class "
        "(e.g. 'langchain_openai.ChatOpenAI')",
    )
    env_key: str = Field(
        description="Environment variable name for the API key "
        "(e.g. 'OPENAI_API_KEY')",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional API base URL override",
    )
    model_field: str = Field(
        default="model",
        description="Constructor parameter name for the model identifier",
    )
    extra_params: dict[str, Any] | None = Field(
        default=None,
        description="Extra keyword arguments passed to the LangChain class constructor",
    )
    supports_vision: bool | None = Field(
        default=None,
        description="Optional provider-level default for image input support",
    )
    model_capabilities: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional exact-match per-model capability overrides",
    )


class AuthProfile(BaseSettings):
    """Authentication profile for API key rotation.

    Multiple AuthProfiles for the same provider enable key-level rotation
    within the FallbackChain before switching to a different provider.

    YAML example:
        auth_profiles:
          - profile_id: "kimi-key-1"
            provider: "kimi"
            env_key: "KIMI_API_KEY_1"
          - profile_id: "kimi-key-2"
            provider: "kimi"
            env_key: "KIMI_API_KEY_2"
            base_url: "https://api.moonshot.cn/v1"
    """

    profile_id: str = Field(description="Unique identifier for this auth profile")
    provider: str = Field(description="Provider name this profile belongs to")
    env_key: str = Field(
        description="Environment variable name for the API key",
    )
    base_url: str | None = Field(
        default=None,
        description="Optional API base URL override for this profile",
    )


class ModelConfig(BaseSettings):
    """Model configuration, nested under SmartClawSettings.model.

    YAML example:
        model:
          primary: "kimi/moonshot-v1-auto"
          fallbacks:
            - "openai/gpt-4o"
            - "anthropic/claude-sonnet-4-20250514"
          temperature: 0.0
          max_tokens: 32768
          auth_profiles:
            - profile_id: "kimi-key-1"
              provider: "kimi"
              env_key: "KIMI_API_KEY_1"
          session_sticky: false
          compaction_model: "openai/gpt-4o-mini"
          identifier_policy: "strict"
          identifier_patterns: []

    Environment variable overrides:
        SMARTCLAW_MODEL__PRIMARY=openai/gpt-4o
        SMARTCLAW_MODEL__TEMPERATURE=0.5
    """

    primary: str = Field(
        default="kimi/kimi-k2.5",
        description="Default model in 'provider/model' format",
    )
    fallbacks: list[str] = Field(
        default=["openai/gpt-4o", "anthropic/claude-sonnet-4-20250514"],
        description="Backup models in priority order",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=32768, gt=0)
    auth_profiles: list[AuthProfile] = Field(
        default_factory=list,
        description="List of AuthProfiles for API key rotation within the same provider",
    )
    session_sticky: bool = Field(
        default=False,
        description="When True, prefer the last successful AuthProfile within a session",
    )
    compaction_model: str | None = Field(
        default=None,
        description="Optional 'provider/model' for the compaction-dedicated LLM "
        "(uses primary model if not set)",
    )
    identifier_policy: str = Field(
        default="strict",
        description="Identifier preservation policy during compaction: "
        "'strict' (preserve all), 'custom' (user patterns), or 'off'",
    )
    identifier_patterns: list[str] = Field(
        default_factory=list,
        description="Custom identifier patterns to preserve when identifier_policy='custom'",
    )


def parse_model_ref(raw: str) -> tuple[str, str]:
    """Parse a 'provider/model' format string, returning (provider, model).

    Args:
        raw: Model reference string in "provider/model" format.

    Returns:
        Tuple of (provider, model).

    Raises:
        ValueError: If the string does not contain exactly one '/'.
    """
    parts = raw.split("/", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = f"Invalid model reference '{raw}': expected 'provider/model' format"
        raise ValueError(msg)
    return parts[0], parts[1]
