"""LLM Provider Factory for SmartClaw.

Creates LangChain ChatModel instances based on provider name,
using ProviderSpec for config-driven dynamic loading via importlib.
"""

from __future__ import annotations

import importlib
import os
from typing import ClassVar

from langchain_core.language_models import BaseChatModel

from smartclaw.providers.config import ProviderSpec

# Kimi API base URL (OpenAI-compatible) — kept for backward compatibility
_KIMI_BASE_URL = "https://api.moonshot.cn/v1"

# GLM API base URL (OpenAI-compatible via modelhub)
_GLM_BASE_URL = "https://modelhub.ailemac.com/v1"


class ProviderFactory:
    """LLM provider factory — creates LangChain ChatModel instances by provider name.

    Uses ProviderSpec definitions (builtin or custom-registered) to dynamically
    import and instantiate LangChain classes via importlib.
    """

    _BUILTIN_SPECS: ClassVar[dict[str, ProviderSpec]] = {
        "openai": ProviderSpec(
            name="openai",
            class_path="langchain_openai.ChatOpenAI",
            env_key="OPENAI_API_KEY",
        ),
        "anthropic": ProviderSpec(
            name="anthropic",
            class_path="langchain_anthropic.ChatAnthropic",
            env_key="ANTHROPIC_API_KEY",
            model_field="model_name",
        ),
        "kimi": ProviderSpec(
            name="kimi",
            class_path="langchain_openai.ChatOpenAI",
            env_key="KIMI_API_KEY",
            base_url=_KIMI_BASE_URL,
        ),
        "glm": ProviderSpec(
            name="glm",
            class_path="langchain_openai.ChatOpenAI",
            env_key="GLM_API_KEY",
            base_url=_GLM_BASE_URL,
        ),
    }

    _custom_specs: ClassVar[dict[str, ProviderSpec]] = {}

    @classmethod
    def register_specs(cls, specs: list[ProviderSpec]) -> None:
        """Register custom ProviderSpecs (from config.yaml), overriding builtins."""
        for spec in specs:
            cls._custom_specs[spec.name] = spec

    @classmethod
    def get_spec(cls, provider: str) -> ProviderSpec:
        """Look up a ProviderSpec: custom > builtin. Raises ValueError if not found."""
        spec = cls._custom_specs.get(provider) or cls._BUILTIN_SPECS.get(provider)
        if spec is None:
            msg = f"Unknown provider: '{provider}'"
            raise ValueError(msg)
        return spec

    @staticmethod
    def create(
        provider: str,
        model: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 32768,
        streaming: bool = False,
    ) -> BaseChatModel:
        """Create a ChatModel instance."""
        spec = ProviderFactory.get_spec(provider)

        resolved_key = api_key or os.environ.get(spec.env_key)
        if resolved_key is None:
            msg = (
                f"API key not provided for provider '{provider}': "
                f"set the '{spec.env_key}' environment variable or pass api_key"
            )
            raise ValueError(msg)

        resolved_base = api_base or spec.base_url

        effective_temperature = temperature
        kimi_extra: dict[str, object] | None = None
        if provider == "kimi" and model.startswith("kimi-k2"):
            effective_temperature = 0.6
            kimi_extra = {"thinking": {"type": "disabled"}}

        cls = _import_class(spec.class_path)

        kwargs: dict[str, object] = {
            spec.model_field: model,
            "temperature": effective_temperature,
            "max_tokens": max_tokens,
            "streaming": streaming,
        }
        if resolved_key is not None:
            kwargs["api_key"] = resolved_key
        if resolved_base is not None:
            kwargs["base_url"] = resolved_base
        if kimi_extra is not None:
            kwargs["extra_body"] = kimi_extra

        if spec.extra_params:
            kwargs.update(spec.extra_params)

        return cls(**kwargs)  # type: ignore[return-value]


def _import_class(class_path: str) -> type:
    """Dynamically import a class from a dotted path."""
    parts = class_path.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        msg = f"Invalid class_path '{class_path}': expected 'module.ClassName' format"
        raise ValueError(msg)
    module_path, class_name = parts
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        msg = f"Cannot import module '{module_path}' from class_path '{class_path}': {exc}"
        raise ValueError(msg) from exc
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        msg = f"Module '{module_path}' has no class '{class_name}' (class_path: '{class_path}')"
        raise ValueError(msg) from exc


VALID_PROVIDERS = frozenset(ProviderFactory._BUILTIN_SPECS.keys())
