"""Property-based tests for ProviderFactory.

Feature: smartclaw-llm-agent-core
"""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from smartclaw.providers.factory import VALID_PROVIDERS, ProviderFactory


# Feature: smartclaw-llm-agent-core, Property 1: Factory creates correctly configured ChatModel instances
class TestFactoryCreatesCorrectInstances:
    """**Validates: Requirements 1.1, 1.4, 4.1**"""

    @given(
        provider=st.sampled_from(["openai", "anthropic", "kimi"]),
        temperature=st.floats(min_value=0.0, max_value=2.0, allow_nan=False),
        max_tokens=st.integers(min_value=1, max_value=131072),
        streaming=st.booleans(),
    )
    @settings(max_examples=100)
    def test_factory_creates_correct_subclass(
        self,
        provider: str,
        temperature: float,
        max_tokens: int,
        streaming: bool,
    ) -> None:
        """For any valid provider, temperature, max_tokens, and streaming flag,
        ProviderFactory.create() returns the correct ChatModel subclass with
        matching parameters."""
        instance = ProviderFactory.create(
            provider,
            "test-model",
            api_key="test-key",
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

        # Check correct subclass
        if provider in ("openai", "kimi"):
            assert isinstance(instance, ChatOpenAI)
        else:
            assert isinstance(instance, ChatAnthropic)

        # Check parameters are reflected
        assert instance.temperature == pytest.approx(temperature)
        assert instance.max_tokens == max_tokens
        assert instance.streaming is streaming


# Feature: smartclaw-llm-agent-core, Property 2: Factory rejects unknown provider names
class TestFactoryRejectsUnknown:
    """**Validates: Requirements 1.2**"""

    @given(
        provider=st.text(min_size=1, max_size=50).filter(lambda s: s not in VALID_PROVIDERS),
    )
    @settings(max_examples=100)
    def test_unknown_provider_raises_value_error(self, provider: str) -> None:
        """For any string not in the valid provider set,
        ProviderFactory.create() raises ValueError containing the provider name."""
        with pytest.raises(ValueError, match=re.escape(provider)):
            ProviderFactory.create(provider, "model", api_key="test-key")
