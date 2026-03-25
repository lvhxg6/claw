"""SmartClaw LLM provider integration layer.

Public API:
    ProviderFactory  — creates LangChain ChatModel instances by provider name
    ModelConfig      — Pydantic Settings model for LLM configuration
    FallbackChain    — ordered failover across provider candidates
    CooldownTracker  — per-provider exponential-backoff cooldown
    parse_model_ref  — split "provider/model" strings
"""

from smartclaw.providers.config import ModelConfig, parse_model_ref
from smartclaw.providers.factory import ProviderFactory
from smartclaw.providers.fallback import CooldownTracker, FallbackChain

__all__ = [
    "CooldownTracker",
    "FallbackChain",
    "ModelConfig",
    "ProviderFactory",
    "parse_model_ref",
]
