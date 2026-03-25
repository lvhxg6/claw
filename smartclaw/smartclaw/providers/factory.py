"""LLM Provider Factory for SmartClaw.

Creates LangChain ChatModel instances based on provider name.
"""

from langchain_core.language_models import BaseChatModel

# Kimi API base URL (OpenAI-compatible)
_KIMI_BASE_URL = "https://api.moonshot.cn/v1"

# Valid provider names
VALID_PROVIDERS = frozenset({"openai", "anthropic", "kimi"})


class ProviderFactory:
    """LLM provider factory — creates LangChain ChatModel instances by provider name."""

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
        """Create a ChatModel instance.

        Supported providers:
        - "openai" → ChatOpenAI
        - "anthropic" → ChatAnthropic
        - "kimi" → ChatOpenAI (with Kimi base_url)

        Args:
            provider: Provider name.
            model: Model name (e.g. "gpt-4o", "moonshot-v1-auto").
            api_key: Optional API key override.
            api_base: Optional API base URL override.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens for generation.
            streaming: Whether to enable streaming.

        Returns:
            Configured BaseChatModel instance.

        Raises:
            ValueError: Unknown provider name.
        """
        if provider == "openai":
            return _create_openai(
                model=model,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        if provider == "kimi":
            return _create_openai(
                model=model,
                api_key=api_key,
                api_base=api_base or _KIMI_BASE_URL,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        if provider == "anthropic":
            return _create_anthropic(
                model=model,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=streaming,
            )
        msg = f"Unknown provider: '{provider}'"
        raise ValueError(msg)


def _create_openai(
    *,
    model: str,
    api_key: str | None,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
    streaming: bool,
) -> BaseChatModel:
    """Create a ChatOpenAI instance."""
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }
    if api_key is not None:
        kwargs["api_key"] = api_key
    if api_base is not None:
        kwargs["base_url"] = api_base
    return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


def _create_anthropic(
    *,
    model: str,
    api_key: str | None,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
    streaming: bool,
) -> BaseChatModel:
    """Create a ChatAnthropic instance."""
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, object] = {
        "model_name": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }
    if api_key is not None:
        kwargs["api_key"] = api_key
    if api_base is not None:
        kwargs["base_url"] = api_base
    return ChatAnthropic(**kwargs)  # type: ignore[arg-type]
