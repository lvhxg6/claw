"""YAML configuration loader and validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
)

from .settings import SmartClawSettings


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Custom pydantic-settings source that reads from a YAML dict.

    This is used to inject YAML file data into the pydantic-settings
    source chain with the correct priority (below env vars).
    """

    def __init__(self, settings_cls: type[BaseSettings], yaml_data: dict[str, Any]) -> None:
        super().__init__(settings_cls)
        self._yaml_data = yaml_data

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        value = self._yaml_data.get(field_name)
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._yaml_data


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (directory containing pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


def load_config(config_path: Path | str | None = None) -> SmartClawSettings:
    """Load YAML configuration and validate via Pydantic Settings.

    Resolution order for config path:
        1. Explicit ``config_path`` argument
        2. ``SMARTCLAW_CONFIG_PATH`` environment variable
        3. ``config/config.yaml`` relative to project root

    Field value priority (highest to lowest):
        1. Environment variables (``SMARTCLAW_`` prefix)
        2. YAML file values
        3. Default field values

    Args:
        config_path: Optional explicit path to the YAML config file.

    Returns:
        Validated SmartClawSettings instance.

    Raises:
        FileNotFoundError: If the resolved config file does not exist.
        yaml.YAMLError: If the YAML file contains syntax errors.
        pydantic.ValidationError: If configuration values fail schema validation.
    """
    resolved_path = _resolve_config_path(config_path)
    yaml_data = _read_yaml(resolved_path)

    # Build a dynamic subclass that injects YAML data as a settings source
    # with lower priority than env vars but higher than defaults.
    yaml_source = yaml_data

    class _ConfiguredSettings(SmartClawSettings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (
                env_settings,
                YamlSettingsSource(settings_cls, yaml_source),
            )

    return _ConfiguredSettings()


def dump_config(settings: SmartClawSettings) -> str:
    """Serialize a SmartClawSettings object to a YAML string.

    Args:
        settings: The settings object to serialize.

    Returns:
        YAML-formatted string representation of the settings.
    """
    data: dict[str, Any] = settings.model_dump()
    result: str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return result


def _resolve_config_path(config_path: Path | str | None) -> Path:
    """Resolve the configuration file path."""
    if config_path is not None:
        return Path(config_path)

    env_path = os.environ.get("SMARTCLAW_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    return _find_project_root() / "config" / "config.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise FileNotFoundError(msg)

    with path.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            msg = f"Failed to parse YAML configuration at {path}: {exc}"
            raise yaml.YAMLError(msg) from exc

    if data is None:
        return {}

    if not isinstance(data, dict):
        msg = f"Expected a YAML mapping at top level, got {type(data).__name__}"
        raise yaml.YAMLError(msg)

    return dict(data)
