"""Provider/model capability resolution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from smartclaw.providers.config import parse_model_ref
from smartclaw.providers.factory import ProviderFactory


class ModelCapabilities(BaseModel):
    """Normalized capability flags for one provider/model pair."""

    supports_vision: bool = False
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_json_mode: bool = False
    max_image_count: int | None = None
    max_image_bytes: int | None = None
    source: str = Field(default="default")


_BUILTIN_MODEL_CAPABILITIES: dict[str, dict[str, dict[str, Any]]] = {
    "openai": {
        "gpt-4o": {"supports_vision": True},
        "gpt-4o-mini": {"supports_vision": True},
    },
    "anthropic": {
        "claude-sonnet-4-20250514": {"supports_vision": True},
        "claude-opus-4-20250514": {"supports_vision": True},
    },
    "kimi": {
        "kimi-k2.5": {"supports_vision": True},
    },
    "glm": {
        "glm-5": {"supports_vision": False},
    },
}


def resolve_model_capabilities(
    *,
    model_ref: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    capability_override: dict[str, Any] | None = None,
    request_override: dict[str, Any] | None = None,
) -> ModelCapabilities:
    """Resolve capabilities for a model using explicit overrides before defaults."""
    resolved_provider, resolved_model = _resolve_provider_model(
        model_ref=model_ref,
        provider=provider,
        model=model,
    )

    if request_override:
        return _merge_capabilities(
            ModelCapabilities(source="request_override"),
            request_override,
            source="request_override",
        )

    if capability_override:
        return _merge_capabilities(
            ModelCapabilities(source="capability_override"),
            capability_override,
            source="capability_override",
        )

    spec = ProviderFactory.get_spec(resolved_provider)
    exact_override = spec.model_capabilities.get(resolved_model)
    if exact_override:
        return _merge_capabilities(
            _provider_default_capabilities(spec),
            exact_override,
            source="provider_model_override",
        )

    builtin_override = _BUILTIN_MODEL_CAPABILITIES.get(resolved_provider, {}).get(resolved_model)
    if builtin_override:
        return _merge_capabilities(
            _provider_default_capabilities(spec),
            builtin_override,
            source="builtin_model_registry",
        )

    if spec.supports_vision is not None:
        return _merge_capabilities(
            ModelCapabilities(),
            {"supports_vision": spec.supports_vision},
            source="provider_default",
        )

    return ModelCapabilities(source="default")


def _resolve_provider_model(
    *,
    model_ref: str | None,
    provider: str | None,
    model: str | None,
) -> tuple[str, str]:
    if model_ref:
        return parse_model_ref(model_ref)
    if provider and model:
        return provider, model
    msg = "Model capability resolution requires either model_ref or both provider and model"
    raise ValueError(msg)


def _provider_default_capabilities(spec: Any) -> ModelCapabilities:
    if spec.supports_vision is None:
        return ModelCapabilities()
    return ModelCapabilities(supports_vision=bool(spec.supports_vision), source="provider_default")


def _merge_capabilities(
    base: ModelCapabilities,
    override: dict[str, Any],
    *,
    source: str,
) -> ModelCapabilities:
    data = base.model_dump()
    for key in ModelCapabilities.model_fields:
        if key == "source":
            continue
        if key in override:
            data[key] = override[key]
    data["source"] = source
    return ModelCapabilities(**data)
