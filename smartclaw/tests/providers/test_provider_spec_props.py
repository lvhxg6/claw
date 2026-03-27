"""Property-based tests for ProviderSpec registration (Properties 1–5).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.providers.config import ProviderSpec
from smartclaw.providers.factory import ProviderFactory


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Safe identifier-like strings for provider names (no whitespace, no slashes)
_provider_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() == s and len(s) > 0)

# Dotted class paths like "some_module.SomeClass"
_class_paths = st.builds(
    lambda mod, cls: f"{mod}.{cls}",
    mod=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
    cls=st.from_regex(r"[A-Z][a-zA-Z0-9]{0,20}", fullmatch=True),
)

# Environment variable key names
_env_keys = st.from_regex(r"[A-Z][A-Z0-9_]{2,20}", fullmatch=True)

# Optional base URLs
_base_urls = st.one_of(
    st.none(),
    st.builds(lambda h: f"https://{h}.example.com/v1", h=st.from_regex(r"[a-z]{3,10}", fullmatch=True)),
)

# model_field names
_model_fields = st.sampled_from(["model", "model_name", "model_id"])

# extra_params dicts (simple JSON-safe values)
_extra_params = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.from_regex(r"[a-z_]{1,10}", fullmatch=True),
        values=st.one_of(st.integers(min_value=0, max_value=1000), st.text(min_size=1, max_size=10)),
        min_size=1,
        max_size=3,
    ),
)

# Full ProviderSpec strategy
_provider_specs = st.builds(
    ProviderSpec,
    name=_provider_names,
    class_path=_class_paths,
    env_key=_env_keys,
    base_url=_base_urls,
    model_field=_model_fields,
    extra_params=_extra_params,
)

# Built-in provider names
_BUILTIN_NAMES = frozenset(ProviderFactory._BUILTIN_SPECS.keys())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_custom_specs():
    """Ensure _custom_specs is clean before and after each test."""
    saved = dict(ProviderFactory._custom_specs)
    ProviderFactory._custom_specs.clear()
    yield
    ProviderFactory._custom_specs.clear()
    ProviderFactory._custom_specs.update(saved)


# ---------------------------------------------------------------------------
# Property 1: ProviderSpec 注册与查找一致性
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 1: ProviderSpec 注册与查找一致性
class TestProviderSpecRegistrationConsistency:
    """**Validates: Requirements 1.1**

    For any list of ProviderSpec objects registered via register_specs,
    calling get_spec(name) should return a matching spec.
    """

    @given(specs=st.lists(_provider_specs, min_size=1, max_size=5))
    @settings(max_examples=100)
    def test_registered_specs_are_retrievable(self, specs: list[ProviderSpec]) -> None:
        """After registering specs, get_spec returns matching spec for each name."""
        ProviderFactory._custom_specs.clear()
        ProviderFactory.register_specs(specs)

        # register_specs processes in order, so last spec with a given name wins
        expected: dict[str, ProviderSpec] = {}
        for spec in specs:
            expected[spec.name] = spec

        for name, spec in expected.items():
            retrieved = ProviderFactory.get_spec(name)
            assert retrieved.name == spec.name
            assert retrieved.class_path == spec.class_path
            assert retrieved.env_key == spec.env_key
            assert retrieved.base_url == spec.base_url
            assert retrieved.model_field == spec.model_field
            assert retrieved.extra_params == spec.extra_params


# ---------------------------------------------------------------------------
# Property 2: ProviderSpec 覆盖内置默认值
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 2: ProviderSpec 覆盖内置默认值
class TestProviderSpecOverridesBuiltin:
    """**Validates: Requirements 1.3**

    For any ProviderSpec whose name matches a built-in, after registering,
    get_spec should return the custom spec (not the built-in default).
    """

    @given(
        builtin_name=st.sampled_from(sorted(_BUILTIN_NAMES)),
        custom_class_path=_class_paths,
        custom_env_key=_env_keys,
    )
    @settings(max_examples=100)
    def test_custom_spec_overrides_builtin(
        self,
        builtin_name: str,
        custom_class_path: str,
        custom_env_key: str,
    ) -> None:
        """Registering a spec with a built-in name overrides the built-in default."""
        ProviderFactory._custom_specs.clear()

        custom_spec = ProviderSpec(
            name=builtin_name,
            class_path=custom_class_path,
            env_key=custom_env_key,
        )
        ProviderFactory.register_specs([custom_spec])

        retrieved = ProviderFactory.get_spec(builtin_name)
        assert retrieved.class_path == custom_class_path
        assert retrieved.env_key == custom_env_key
        # Confirm it's NOT the builtin
        builtin = ProviderFactory._BUILTIN_SPECS[builtin_name]
        if custom_class_path != builtin.class_path:
            assert retrieved.class_path != builtin.class_path


# ---------------------------------------------------------------------------
# Property 3: 无效 class_path 抛出 ValueError
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 3: 无效 class_path 抛出 ValueError
class TestInvalidClassPathRaisesValueError:
    """**Validates: Requirements 1.5**

    For any provider with non-existent class_path, create() should raise ValueError.
    """

    @given(
        provider_name=_provider_names.filter(lambda n: n not in _BUILTIN_NAMES),
        bad_module=st.from_regex(r"nonexistent_module_[a-z]{3,8}", fullmatch=True),
        class_name=st.from_regex(r"[A-Z][a-zA-Z]{2,10}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_nonexistent_module_raises_value_error(
        self,
        provider_name: str,
        bad_module: str,
        class_name: str,
    ) -> None:
        """create() raises ValueError when class_path module doesn't exist."""
        ProviderFactory._custom_specs.clear()

        bad_class_path = f"{bad_module}.{class_name}"
        spec = ProviderSpec(
            name=provider_name,
            class_path=bad_class_path,
            env_key="FAKE_API_KEY",
        )
        ProviderFactory.register_specs([spec])

        # Set the env var so we don't fail on missing API key first
        with patch.dict(os.environ, {"FAKE_API_KEY": "test-key"}):
            with pytest.raises(ValueError, match=bad_module):
                ProviderFactory.create(provider_name, "test-model")


# ---------------------------------------------------------------------------
# Property 4: 缺失 API Key 抛出 ValueError
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 4: 缺失 API Key 抛出 ValueError
class TestMissingApiKeyRaisesValueError:
    """**Validates: Requirements 1.6**

    For any ProviderSpec whose env_key is not set and no api_key provided,
    create() should raise ValueError mentioning the env variable.
    """

    @given(
        provider_name=_provider_names.filter(lambda n: n not in _BUILTIN_NAMES),
        env_key=_env_keys,
    )
    @settings(max_examples=100)
    def test_missing_env_key_raises_value_error(
        self,
        provider_name: str,
        env_key: str,
    ) -> None:
        """create() raises ValueError when env_key is unset and no api_key given."""
        ProviderFactory._custom_specs.clear()

        spec = ProviderSpec(
            name=provider_name,
            class_path="langchain_openai.ChatOpenAI",
            env_key=env_key,
        )
        ProviderFactory.register_specs([spec])

        # Ensure the env var is NOT set
        env_patch = {env_key: ""} if env_key in os.environ else {}
        with patch.dict(os.environ, env_patch, clear=False):
            os.environ.pop(env_key, None)
            with pytest.raises(ValueError, match=env_key):
                ProviderFactory.create(provider_name, "test-model")


# ---------------------------------------------------------------------------
# Property 5: extra_params 透传
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 5: extra_params 透传
class TestExtraParamsPassthrough:
    """**Validates: Requirements 1.7**

    For any ProviderSpec with non-empty extra_params, the params should be
    passed to the constructor.
    """

    @given(
        provider_name=_provider_names.filter(lambda n: n not in _BUILTIN_NAMES),
        extra_params=st.dictionaries(
            keys=st.from_regex(r"[a-z_]{1,10}", fullmatch=True),
            values=st.integers(min_value=0, max_value=1000),
            min_size=1,
            max_size=3,
        ),
    )
    @settings(max_examples=100)
    def test_extra_params_passed_to_constructor(
        self,
        provider_name: str,
        extra_params: dict[str, Any],
    ) -> None:
        """extra_params from ProviderSpec are passed through to the LangChain class constructor."""
        ProviderFactory._custom_specs.clear()

        spec = ProviderSpec(
            name=provider_name,
            class_path="fake_module.FakeLLM",
            env_key="FAKE_API_KEY",
            extra_params=extra_params,
        )
        ProviderFactory.register_specs([spec])

        # Capture kwargs passed to the constructor
        captured_kwargs: dict[str, Any] = {}

        class _FakeLLM:
            def __init__(self, **kwargs: Any) -> None:
                captured_kwargs.update(kwargs)

        with (
            patch.dict(os.environ, {"FAKE_API_KEY": "test-key"}),
            patch(
                "smartclaw.providers.factory._import_class",
                return_value=_FakeLLM,
            ),
        ):
            ProviderFactory.create(provider_name, "test-model", api_key="test-key")

        # Verify extra_params were passed through
        for key, value in extra_params.items():
            assert captured_kwargs.get(key) == value, (
                f"extra_param '{key}={value}' not found in constructor kwargs: {captured_kwargs}"
            )
