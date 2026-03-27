"""Unit tests for Memory Enhancement configuration settings.

Tests cover:
- MemorySettings new fields defaults (memory_file_enabled, memory_dir_enabled, chunk_tokens, etc.)
- BootstrapSettings defaults (enabled, max_file_size)
- SkillsSettings hot reload fields (hot_reload, debounce_ms)
- ConfigSettings hot reload fields (hot_reload, debounce_ms)
- Type validation for all fields
- Boundary conditions for numeric fields

Requirements: 1.5, 2.6, 3.7, 4.8
"""

from __future__ import annotations

import os

import pytest

from smartclaw.config.settings import (
    BootstrapSettings,
    ConfigSettings,
    MemorySettings,
    SkillsSettings,
    SmartClawSettings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_smartclaw_env() -> dict[str, str]:
    """Remove all SMARTCLAW_ env vars, return saved values for restore."""
    saved: dict[str, str] = {}
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    """Restore previously saved env vars."""
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v


# ---------------------------------------------------------------------------
# Test: MemorySettings new fields defaults (Req 1.5)
# ---------------------------------------------------------------------------


class TestMemorySettingsEnhancementDefaults:
    """Verify MemorySettings new field default values for memory enhancement."""

    def test_memory_file_enabled_default_true(self) -> None:
        """memory_file_enabled should default to True."""
        s = MemorySettings()
        assert s.memory_file_enabled is True

    def test_memory_dir_enabled_default_true(self) -> None:
        """memory_dir_enabled should default to True."""
        s = MemorySettings()
        assert s.memory_dir_enabled is True

    def test_chunk_tokens_default_512(self) -> None:
        """chunk_tokens should default to 512."""
        s = MemorySettings()
        assert s.chunk_tokens == 512

    def test_chunk_overlap_default_64(self) -> None:
        """chunk_overlap should default to 64."""
        s = MemorySettings()
        assert s.chunk_overlap == 64

    def test_max_file_size_default_2mb(self) -> None:
        """max_file_size should default to 2MB (2 * 1024 * 1024)."""
        s = MemorySettings()
        assert s.max_file_size == 2 * 1024 * 1024

    def test_max_dir_size_default_50mb(self) -> None:
        """max_dir_size should default to 50MB (50 * 1024 * 1024)."""
        s = MemorySettings()
        assert s.max_dir_size == 50 * 1024 * 1024

    def test_embedding_provider_default_auto(self) -> None:
        """embedding_provider should default to 'auto'."""
        s = MemorySettings()
        assert s.embedding_provider == "auto"

    def test_vector_weight_default_0_7(self) -> None:
        """vector_weight should default to 0.7."""
        s = MemorySettings()
        assert s.vector_weight == 0.7

    def test_text_weight_default_0_3(self) -> None:
        """text_weight should default to 0.3."""
        s = MemorySettings()
        assert s.text_weight == 0.3

    def test_top_k_default_5(self) -> None:
        """top_k should default to 5."""
        s = MemorySettings()
        assert s.top_k == 5

    def test_auto_extract_default_false(self) -> None:
        """auto_extract should default to False."""
        s = MemorySettings()
        assert s.auto_extract is False

    def test_max_facts_default_100(self) -> None:
        """max_facts should default to 100."""
        s = MemorySettings()
        assert s.max_facts == 100

    def test_fact_confidence_threshold_default_0_7(self) -> None:
        """fact_confidence_threshold should default to 0.7."""
        s = MemorySettings()
        assert s.fact_confidence_threshold == 0.7


# ---------------------------------------------------------------------------
# Test: BootstrapSettings defaults (Req 2.6)
# ---------------------------------------------------------------------------


class TestBootstrapSettingsDefaults:
    """Verify BootstrapSettings default values."""

    def test_enabled_default_true(self) -> None:
        """enabled should default to True."""
        s = BootstrapSettings()
        assert s.enabled is True

    def test_max_file_size_default_512kb(self) -> None:
        """max_file_size should default to 512KB (512 * 1024)."""
        s = BootstrapSettings()
        assert s.max_file_size == 512 * 1024


# ---------------------------------------------------------------------------
# Test: SkillsSettings hot reload fields (Req 3.7)
# ---------------------------------------------------------------------------


class TestSkillsSettingsHotReloadDefaults:
    """Verify SkillsSettings hot reload field default values."""

    def test_hot_reload_default_true(self) -> None:
        """hot_reload should default to True."""
        s = SkillsSettings()
        assert s.hot_reload is True

    def test_debounce_ms_default_250(self) -> None:
        """debounce_ms should default to 250."""
        s = SkillsSettings()
        assert s.debounce_ms == 250


# ---------------------------------------------------------------------------
# Test: ConfigSettings defaults (Req 4.8)
# ---------------------------------------------------------------------------


class TestConfigSettingsDefaults:
    """Verify ConfigSettings default values."""

    def test_hot_reload_default_true(self) -> None:
        """hot_reload should default to True."""
        s = ConfigSettings()
        assert s.hot_reload is True

    def test_debounce_ms_default_500(self) -> None:
        """debounce_ms should default to 500."""
        s = ConfigSettings()
        assert s.debounce_ms == 500


# ---------------------------------------------------------------------------
# Test: SmartClawSettings includes enhancement fields
# ---------------------------------------------------------------------------


class TestSmartClawSettingsEnhancementFields:
    """Verify enhancement fields are present on SmartClawSettings."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_bootstrap_field_present(self) -> None:
        """bootstrap field should be present with correct type."""
        s = SmartClawSettings()
        assert isinstance(s.bootstrap, BootstrapSettings)

    def test_bootstrap_defaults(self) -> None:
        """bootstrap field should have correct defaults."""
        s = SmartClawSettings()
        assert s.bootstrap.enabled is True
        assert s.bootstrap.max_file_size == 512 * 1024

    def test_config_field_present(self) -> None:
        """config field should be present with correct type."""
        s = SmartClawSettings()
        assert isinstance(s.config, ConfigSettings)

    def test_config_defaults(self) -> None:
        """config field should have correct defaults."""
        s = SmartClawSettings()
        assert s.config.hot_reload is True
        assert s.config.debounce_ms == 500

    def test_memory_enhancement_fields(self) -> None:
        """memory field should have enhancement fields with correct defaults."""
        s = SmartClawSettings()
        assert s.memory.memory_file_enabled is True
        assert s.memory.memory_dir_enabled is True
        assert s.memory.chunk_tokens == 512
        assert s.memory.chunk_overlap == 64
        assert s.memory.max_file_size == 2 * 1024 * 1024
        assert s.memory.max_dir_size == 50 * 1024 * 1024

    def test_memory_vector_search_fields(self) -> None:
        """memory field should have vector search fields with correct defaults."""
        s = SmartClawSettings()
        assert s.memory.embedding_provider == "auto"
        assert s.memory.vector_weight == 0.7
        assert s.memory.text_weight == 0.3
        assert s.memory.top_k == 5

    def test_memory_fact_extraction_fields(self) -> None:
        """memory field should have fact extraction fields with correct defaults."""
        s = SmartClawSettings()
        assert s.memory.auto_extract is False
        assert s.memory.max_facts == 100
        assert s.memory.fact_confidence_threshold == 0.7

    def test_skills_hot_reload_fields(self) -> None:
        """skills field should have hot reload fields with correct defaults."""
        s = SmartClawSettings()
        assert s.skills.hot_reload is True
        assert s.skills.debounce_ms == 250


# ---------------------------------------------------------------------------
# Test: Type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    """Verify type validation for configuration fields."""

    def test_memory_settings_bool_fields(self) -> None:
        """Boolean fields should accept bool values."""
        s = MemorySettings(
            memory_file_enabled=False,
            memory_dir_enabled=False,
            auto_extract=True,
        )
        assert s.memory_file_enabled is False
        assert s.memory_dir_enabled is False
        assert s.auto_extract is True

    def test_memory_settings_int_fields(self) -> None:
        """Integer fields should accept int values."""
        s = MemorySettings(
            chunk_tokens=1024,
            chunk_overlap=128,
            max_file_size=4 * 1024 * 1024,
            max_dir_size=100 * 1024 * 1024,
            top_k=10,
            max_facts=200,
        )
        assert s.chunk_tokens == 1024
        assert s.chunk_overlap == 128
        assert s.max_file_size == 4 * 1024 * 1024
        assert s.max_dir_size == 100 * 1024 * 1024
        assert s.top_k == 10
        assert s.max_facts == 200

    def test_memory_settings_float_fields(self) -> None:
        """Float fields should accept float values."""
        s = MemorySettings(
            vector_weight=0.5,
            text_weight=0.5,
            fact_confidence_threshold=0.8,
        )
        assert s.vector_weight == 0.5
        assert s.text_weight == 0.5
        assert s.fact_confidence_threshold == 0.8

    def test_memory_settings_str_fields(self) -> None:
        """String fields should accept str values."""
        s = MemorySettings(embedding_provider="openai")
        assert s.embedding_provider == "openai"

    def test_bootstrap_settings_bool_fields(self) -> None:
        """Boolean fields should accept bool values."""
        s = BootstrapSettings(enabled=False)
        assert s.enabled is False

    def test_bootstrap_settings_int_fields(self) -> None:
        """Integer fields should accept int values."""
        s = BootstrapSettings(max_file_size=1024 * 1024)
        assert s.max_file_size == 1024 * 1024

    def test_skills_settings_bool_fields(self) -> None:
        """Boolean fields should accept bool values."""
        s = SkillsSettings(hot_reload=False)
        assert s.hot_reload is False

    def test_skills_settings_int_fields(self) -> None:
        """Integer fields should accept int values."""
        s = SkillsSettings(debounce_ms=500)
        assert s.debounce_ms == 500

    def test_config_settings_bool_fields(self) -> None:
        """Boolean fields should accept bool values."""
        s = ConfigSettings(hot_reload=False)
        assert s.hot_reload is False

    def test_config_settings_int_fields(self) -> None:
        """Integer fields should accept int values."""
        s = ConfigSettings(debounce_ms=1000)
        assert s.debounce_ms == 1000


# ---------------------------------------------------------------------------
# Test: Boundary conditions
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """Verify boundary conditions for numeric fields."""

    def test_chunk_tokens_zero(self) -> None:
        """chunk_tokens can be set to 0."""
        s = MemorySettings(chunk_tokens=0)
        assert s.chunk_tokens == 0

    def test_chunk_tokens_large_value(self) -> None:
        """chunk_tokens can be set to large values."""
        s = MemorySettings(chunk_tokens=10000)
        assert s.chunk_tokens == 10000

    def test_chunk_overlap_zero(self) -> None:
        """chunk_overlap can be set to 0."""
        s = MemorySettings(chunk_overlap=0)
        assert s.chunk_overlap == 0

    def test_max_file_size_zero(self) -> None:
        """max_file_size can be set to 0."""
        s = MemorySettings(max_file_size=0)
        assert s.max_file_size == 0

    def test_max_file_size_large_value(self) -> None:
        """max_file_size can be set to large values."""
        s = MemorySettings(max_file_size=1024 * 1024 * 1024)  # 1GB
        assert s.max_file_size == 1024 * 1024 * 1024

    def test_max_dir_size_zero(self) -> None:
        """max_dir_size can be set to 0."""
        s = MemorySettings(max_dir_size=0)
        assert s.max_dir_size == 0

    def test_vector_weight_zero(self) -> None:
        """vector_weight can be set to 0."""
        s = MemorySettings(vector_weight=0.0)
        assert s.vector_weight == 0.0

    def test_vector_weight_one(self) -> None:
        """vector_weight can be set to 1.0."""
        s = MemorySettings(vector_weight=1.0)
        assert s.vector_weight == 1.0

    def test_text_weight_zero(self) -> None:
        """text_weight can be set to 0."""
        s = MemorySettings(text_weight=0.0)
        assert s.text_weight == 0.0

    def test_text_weight_one(self) -> None:
        """text_weight can be set to 1.0."""
        s = MemorySettings(text_weight=1.0)
        assert s.text_weight == 1.0

    def test_top_k_zero(self) -> None:
        """top_k can be set to 0."""
        s = MemorySettings(top_k=0)
        assert s.top_k == 0

    def test_top_k_large_value(self) -> None:
        """top_k can be set to large values."""
        s = MemorySettings(top_k=100)
        assert s.top_k == 100

    def test_max_facts_zero(self) -> None:
        """max_facts can be set to 0."""
        s = MemorySettings(max_facts=0)
        assert s.max_facts == 0

    def test_fact_confidence_threshold_zero(self) -> None:
        """fact_confidence_threshold can be set to 0."""
        s = MemorySettings(fact_confidence_threshold=0.0)
        assert s.fact_confidence_threshold == 0.0

    def test_fact_confidence_threshold_one(self) -> None:
        """fact_confidence_threshold can be set to 1.0."""
        s = MemorySettings(fact_confidence_threshold=1.0)
        assert s.fact_confidence_threshold == 1.0

    def test_bootstrap_max_file_size_zero(self) -> None:
        """bootstrap max_file_size can be set to 0."""
        s = BootstrapSettings(max_file_size=0)
        assert s.max_file_size == 0

    def test_skills_debounce_ms_zero(self) -> None:
        """skills debounce_ms can be set to 0."""
        s = SkillsSettings(debounce_ms=0)
        assert s.debounce_ms == 0

    def test_skills_debounce_ms_large_value(self) -> None:
        """skills debounce_ms can be set to large values."""
        s = SkillsSettings(debounce_ms=10000)
        assert s.debounce_ms == 10000

    def test_config_debounce_ms_zero(self) -> None:
        """config debounce_ms can be set to 0."""
        s = ConfigSettings(debounce_ms=0)
        assert s.debounce_ms == 0

    def test_config_debounce_ms_large_value(self) -> None:
        """config debounce_ms can be set to large values."""
        s = ConfigSettings(debounce_ms=10000)
        assert s.debounce_ms == 10000


# ---------------------------------------------------------------------------
# Test: Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnhancementEnvOverrides:
    """Verify environment variable overrides for enhancement settings."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_memory_file_enabled_override(self) -> None:
        """memory_file_enabled can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__MEMORY_FILE_ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.memory.memory_file_enabled is False

    def test_memory_dir_enabled_override(self) -> None:
        """memory_dir_enabled can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__MEMORY_DIR_ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.memory.memory_dir_enabled is False

    def test_chunk_tokens_override(self) -> None:
        """chunk_tokens can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__CHUNK_TOKENS"] = "1024"
        s = SmartClawSettings()
        assert s.memory.chunk_tokens == 1024

    def test_chunk_overlap_override(self) -> None:
        """chunk_overlap can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__CHUNK_OVERLAP"] = "128"
        s = SmartClawSettings()
        assert s.memory.chunk_overlap == 128

    def test_max_file_size_override(self) -> None:
        """max_file_size can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__MAX_FILE_SIZE"] = "4194304"  # 4MB
        s = SmartClawSettings()
        assert s.memory.max_file_size == 4194304

    def test_max_dir_size_override(self) -> None:
        """max_dir_size can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__MAX_DIR_SIZE"] = "104857600"  # 100MB
        s = SmartClawSettings()
        assert s.memory.max_dir_size == 104857600

    def test_embedding_provider_override(self) -> None:
        """embedding_provider can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__EMBEDDING_PROVIDER"] = "openai"
        s = SmartClawSettings()
        assert s.memory.embedding_provider == "openai"

    def test_vector_weight_override(self) -> None:
        """vector_weight can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__VECTOR_WEIGHT"] = "0.5"
        s = SmartClawSettings()
        assert s.memory.vector_weight == 0.5

    def test_text_weight_override(self) -> None:
        """text_weight can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__TEXT_WEIGHT"] = "0.5"
        s = SmartClawSettings()
        assert s.memory.text_weight == 0.5

    def test_top_k_override(self) -> None:
        """top_k can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__TOP_K"] = "10"
        s = SmartClawSettings()
        assert s.memory.top_k == 10

    def test_auto_extract_override(self) -> None:
        """auto_extract can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__AUTO_EXTRACT"] = "true"
        s = SmartClawSettings()
        assert s.memory.auto_extract is True

    def test_max_facts_override(self) -> None:
        """max_facts can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__MAX_FACTS"] = "200"
        s = SmartClawSettings()
        assert s.memory.max_facts == 200

    def test_fact_confidence_threshold_override(self) -> None:
        """fact_confidence_threshold can be overridden via env var."""
        os.environ["SMARTCLAW_MEMORY__FACT_CONFIDENCE_THRESHOLD"] = "0.8"
        s = SmartClawSettings()
        assert s.memory.fact_confidence_threshold == 0.8

    def test_bootstrap_enabled_override(self) -> None:
        """bootstrap.enabled can be overridden via env var."""
        os.environ["SMARTCLAW_BOOTSTRAP__ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.bootstrap.enabled is False

    def test_bootstrap_max_file_size_override(self) -> None:
        """bootstrap.max_file_size can be overridden via env var."""
        os.environ["SMARTCLAW_BOOTSTRAP__MAX_FILE_SIZE"] = "1048576"  # 1MB
        s = SmartClawSettings()
        assert s.bootstrap.max_file_size == 1048576

    def test_skills_hot_reload_override(self) -> None:
        """skills.hot_reload can be overridden via env var."""
        os.environ["SMARTCLAW_SKILLS__HOT_RELOAD"] = "false"
        s = SmartClawSettings()
        assert s.skills.hot_reload is False

    def test_skills_debounce_ms_override(self) -> None:
        """skills.debounce_ms can be overridden via env var."""
        os.environ["SMARTCLAW_SKILLS__DEBOUNCE_MS"] = "500"
        s = SmartClawSettings()
        assert s.skills.debounce_ms == 500

    def test_config_hot_reload_override(self) -> None:
        """config.hot_reload can be overridden via env var."""
        os.environ["SMARTCLAW_CONFIG__HOT_RELOAD"] = "false"
        s = SmartClawSettings()
        assert s.config.hot_reload is False

    def test_config_debounce_ms_override(self) -> None:
        """config.debounce_ms can be overridden via env var."""
        os.environ["SMARTCLAW_CONFIG__DEBOUNCE_MS"] = "1000"
        s = SmartClawSettings()
        assert s.config.debounce_ms == 1000

    def test_existing_fields_unchanged_with_enhancement_overrides(self) -> None:
        """Existing P0/P1 fields retain defaults when enhancement env vars are set."""
        os.environ["SMARTCLAW_MEMORY__CHUNK_TOKENS"] = "1024"
        os.environ["SMARTCLAW_BOOTSTRAP__ENABLED"] = "false"
        os.environ["SMARTCLAW_SKILLS__HOT_RELOAD"] = "false"
        os.environ["SMARTCLAW_CONFIG__HOT_RELOAD"] = "false"
        s = SmartClawSettings()
        # Existing P0/P1 defaults intact
        assert s.agent_defaults.max_tokens == 32768
        assert s.logging.level == "INFO"
        assert s.memory.enabled is True
        assert s.memory.db_path == "~/.smartclaw/memory.db"
        assert s.skills.enabled is True
        assert s.sub_agent.enabled is True
