"""Model configuration and reference parsing for SmartClaw LLM providers."""

from pydantic import Field
from pydantic_settings import BaseSettings


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
