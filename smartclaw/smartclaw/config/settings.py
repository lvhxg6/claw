"""Pydantic Settings schema definitions for SmartClaw configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings

from smartclaw.browser.engine import BrowserConfig
from smartclaw.providers.config import ModelConfig


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level: DEBUG | INFO | WARNING | ERROR | CRITICAL")
    format: str = Field(default="console", description="Output format: console | json")
    file: str | None = Field(default=None, description="Log file path, None means no file logging")


class AgentDefaultsSettings(BaseSettings):
    """Agent default configuration."""

    workspace: str = Field(default="~/.smartclaw/workspace", description="Agent workspace directory")
    max_tokens: int = Field(default=32768, description="Maximum token count")
    max_tool_iterations: int = Field(default=50, description="Maximum tool call iterations")


class CredentialSettings(BaseSettings):
    """Credential management configuration."""

    keyring_service: str = Field(default="smartclaw", description="Keyring service name")


class SmartClawSettings(BaseSettings):
    """SmartClaw root configuration schema.

    Supports environment variable overrides with SMARTCLAW_ prefix
    and nested delimiter __ (double underscore).

    Examples:
        SMARTCLAW_LOGGING__LEVEL=DEBUG
        SMARTCLAW_AGENT_DEFAULTS__MAX_TOKENS=65536
    """

    model_config = {"env_prefix": "SMARTCLAW_", "env_nested_delimiter": "__"}

    agent_defaults: AgentDefaultsSettings = Field(default_factory=AgentDefaultsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    credentials: CredentialSettings = Field(default_factory=CredentialSettings)
    model: ModelConfig = Field(default_factory=ModelConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
