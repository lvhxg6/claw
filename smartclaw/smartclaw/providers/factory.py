"""LLM Provider Factory for SmartClaw.

Creates LangChain ChatModel instances based on provider name.
"""

import os

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
            # Auto-resolve Kimi API key from KIMI_API_KEY env var
            resolved_key = api_key or os.environ.get("KIMI_API_KEY")
            # Kimi K2 series: disable thinking mode (avoids reasoning_content
            # round-trip issue with LangChain) and use required temperature
            is_k2 = model.startswith("kimi-k2")
            kimi_temp = 0.6 if is_k2 else temperature
            kimi_extra = {"thinking": {"type": "disabled"}} if is_k2 else None
            return _create_openai(
                model=model,
                api_key=resolved_key,
                api_base=api_base or _KIMI_BASE_URL,
                temperature=kimi_temp,
                max_tokens=max_tokens,
                streaming=streaming,
                extra_body=kimi_extra,
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
    extra_body: dict[str, object] | None = None,
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
    if extra_body is not None:
        kwargs["extra_body"] = extra_body
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
