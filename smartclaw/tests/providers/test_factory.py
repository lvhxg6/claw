"""Unit tests for ProviderFactory."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from smartclaw.providers.factory import _KIMI_BASE_URL, ProviderFactory


class TestProviderFactoryOpenAI:
    """Test OpenAI provider creation."""

    def test_creates_chat_openai(self) -> None:
        instance = ProviderFactory.create("openai", "gpt-4o", api_key="test-key")
        assert isinstance(instance, ChatOpenAI)

    def test_openai_model_name(self) -> None:
        instance = ProviderFactory.create("openai", "gpt-4o", api_key="test-key")
        assert isinstance(instance, ChatOpenAI)
        assert instance.model_name == "gpt-4o"

    def test_openai_temperature(self) -> None:
        instance = ProviderFactory.create("openai", "gpt-4o", api_key="test-key", temperature=0.7)
        assert isinstance(instance, ChatOpenAI)
        assert instance.temperature == pytest.approx(0.7)

    def test_openai_max_tokens(self) -> None:
        instance = ProviderFactory.create("openai", "gpt-4o", api_key="test-key", max_tokens=4096)
        assert isinstance(instance, ChatOpenAI)
        assert instance.max_tokens == 4096

    def test_openai_streaming(self) -> None:
        instance = ProviderFactory.create("openai", "gpt-4o", api_key="test-key", streaming=True)
        assert isinstance(instance, ChatOpenAI)
        assert instance.streaming is True


class TestProviderFactoryAnthropic:
    """Test Anthropic provider creation."""

    def test_creates_chat_anthropic(self) -> None:
        instance = ProviderFactory.create("anthropic", "claude-sonnet-4-20250514", api_key="test-key")
        assert isinstance(instance, ChatAnthropic)

    def test_anthropic_model_name(self) -> None:
        instance = ProviderFactory.create("anthropic", "claude-sonnet-4-20250514", api_key="test-key")
        assert isinstance(instance, ChatAnthropic)
        assert instance.model == "claude-sonnet-4-20250514"

    def test_anthropic_temperature(self) -> None:
        instance = ProviderFactory.create("anthropic", "claude-sonnet-4-20250514", api_key="test-key", temperature=0.5)
        assert isinstance(instance, ChatAnthropic)
        assert instance.temperature == pytest.approx(0.5)

    def test_anthropic_max_tokens(self) -> None:
        instance = ProviderFactory.create(
            "anthropic", "claude-sonnet-4-20250514", api_key="test-key", max_tokens=8192
        )
        assert isinstance(instance, ChatAnthropic)
        assert instance.max_tokens == 8192

    def test_anthropic_streaming(self) -> None:
        instance = ProviderFactory.create(
            "anthropic", "claude-sonnet-4-20250514", api_key="test-key", streaming=True
        )
        assert isinstance(instance, ChatAnthropic)
        assert instance.streaming is True


class TestProviderFactoryKimi:
    """Test Kimi provider creation."""

    def test_creates_chat_openai_for_kimi(self) -> None:
        instance = ProviderFactory.create("kimi", "moonshot-v1-auto", api_key="test-key")
        assert isinstance(instance, ChatOpenAI)

    def test_kimi_base_url(self) -> None:
        instance = ProviderFactory.create("kimi", "moonshot-v1-auto", api_key="test-key")
        assert isinstance(instance, ChatOpenAI)
        base_url = str(instance.openai_api_base)
        assert _KIMI_BASE_URL in base_url

    def test_kimi_custom_base_url(self) -> None:
        custom_url = "https://custom.kimi.api/v1"
        instance = ProviderFactory.create("kimi", "moonshot-v1-auto", api_key="test-key", api_base=custom_url)
        assert isinstance(instance, ChatOpenAI)
        base_url = str(instance.openai_api_base)
        assert custom_url in base_url


class TestProviderFactoryErrors:
    """Test error handling."""

    def test_unknown_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider: 'unknown'"):
            ProviderFactory.create("unknown", "some-model", api_key="test-key")

    def test_error_message_contains_provider_name(self) -> None:
        with pytest.raises(ValueError, match="my-custom-provider"):
            ProviderFactory.create("my-custom-provider", "model", api_key="test-key")
