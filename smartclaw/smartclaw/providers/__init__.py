"""SmartClaw LLM provider integration layer.

Public API:
    ProviderFactory  — creates LangChain ChatModel instances by provider name
    ProviderSpec     — declarative provider specification for config-driven registration
    AuthProfile      — authentication profile for API key rotation
    ModelConfig      — Pydantic Settings model for LLM configuration
    FallbackChain    — ordered failover across provider candidates
    FallbackCandidate — candidate provider/model/profile_id for fallback
    CooldownTracker  — per-provider exponential-backoff cooldown
    parse_model_ref  — split "provider/model" strings
"""

from smartclaw.providers.config import AuthProfile, ModelConfig, ProviderSpec, parse_model_ref
from smartclaw.providers.factory import ProviderFactory
from smartclaw.providers.fallback import CooldownTracker, FallbackCandidate, FallbackChain

__all__ = [
    "AuthProfile",
    "CooldownTracker",
    "FallbackCandidate",
    "FallbackChain",
    "ModelConfig",
    "ProviderFactory",
    "ProviderSpec",
    "parse_model_ref",
]
