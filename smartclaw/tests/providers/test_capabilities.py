"""Unit tests for model capability resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from smartclaw.agent.runtime import AgentRuntime
from smartclaw.providers.capabilities import ModelCapabilities, resolve_model_capabilities
from smartclaw.providers.config import ModelConfig, ProviderSpec
from smartclaw.providers.factory import ProviderFactory
from smartclaw.tools.registry import ToolRegistry


def test_builtin_registry_marks_openai_gpt4o_as_vision() -> None:
    caps = resolve_model_capabilities(model_ref="openai/gpt-4o")
    assert caps.supports_vision is True
    assert caps.source == "builtin_model_registry"


def test_builtin_registry_marks_kimi_k2_5_as_vision() -> None:
    caps = resolve_model_capabilities(model_ref="kimi/kimi-k2.5")
    assert caps.supports_vision is True
    assert caps.source == "builtin_model_registry"


def test_builtin_registry_marks_glm_5_as_non_vision() -> None:
    caps = resolve_model_capabilities(model_ref="glm/glm-5")
    assert caps.supports_vision is False
    assert caps.source == "builtin_model_registry"


def test_builtin_registry_defaults_unknown_model_to_non_vision() -> None:
    caps = resolve_model_capabilities(model_ref="kimi/unknown-model")
    assert caps.supports_vision is False
    assert caps.source == "default"


def test_provider_default_supports_vision_is_used_for_custom_provider() -> None:
    saved = dict(ProviderFactory._custom_specs)
    try:
        ProviderFactory._custom_specs.clear()
        ProviderFactory.register_specs(
            [
                ProviderSpec(
                    name="visionx",
                    class_path="langchain_openai.ChatOpenAI",
                    env_key="VISIONX_API_KEY",
                    supports_vision=True,
                )
            ]
        )
        caps = resolve_model_capabilities(model_ref="visionx/pro-model")
        assert caps.supports_vision is True
        assert caps.source == "provider_default"
    finally:
        ProviderFactory._custom_specs.clear()
        ProviderFactory._custom_specs.update(saved)


def test_provider_exact_model_capability_override_wins() -> None:
    saved = dict(ProviderFactory._custom_specs)
    try:
        ProviderFactory._custom_specs.clear()
        ProviderFactory.register_specs(
            [
                ProviderSpec(
                    name="mixedvision",
                    class_path="langchain_openai.ChatOpenAI",
                    env_key="MIXEDVISION_API_KEY",
                    supports_vision=False,
                    model_capabilities={
                        "vision-pro": {"supports_vision": True, "max_image_count": 4},
                    },
                )
            ]
        )
        caps = resolve_model_capabilities(model_ref="mixedvision/vision-pro")
        assert caps.supports_vision is True
        assert caps.max_image_count == 4
        assert caps.source == "provider_model_override"
    finally:
        ProviderFactory._custom_specs.clear()
        ProviderFactory._custom_specs.update(saved)


def test_request_override_wins_over_registry() -> None:
    caps = resolve_model_capabilities(
        model_ref="openai/gpt-4o",
        request_override={"supports_vision": False},
    )
    assert caps.supports_vision is False
    assert caps.source == "request_override"


def test_runtime_resolve_model_capabilities_uses_primary_when_missing() -> None:
    runtime = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=None,
        summarizer=None,
        system_prompt="test",
        mcp_manager=None,
        model_config=ModelConfig(primary="openai/gpt-4o"),
    )

    caps = runtime.resolve_model_capabilities()
    assert isinstance(caps, ModelCapabilities)
    assert caps.supports_vision is True
