"""Pydantic Settings schema definitions for SmartClaw configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings

from smartclaw.browser.engine import BrowserConfig
from smartclaw.mcp.config import MCPConfig
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


# ---------------------------------------------------------------------------
# P1 Settings models
# ---------------------------------------------------------------------------


class MemorySettings(BaseSettings):
    """Memory module configuration."""

    enabled: bool = True
    db_path: str = "~/.smartclaw/memory.db"
    summary_threshold: int = 20
    keep_recent: int = 5
    summarize_token_percent: int = 70
    context_window: int = 128_000


class SkillsSettings(BaseSettings):
    """Skills module configuration."""

    enabled: bool = True
    workspace_dir: str = "{workspace}/skills"
    global_dir: str = "~/.smartclaw/skills"


class SubAgentSettings(BaseSettings):
    """Sub-agent configuration."""

    enabled: bool = True
    max_depth: int = 3
    max_concurrent: int = 5
    default_timeout_seconds: int = 300
    concurrency_timeout_seconds: int = 30


class AgentRoleConfig(BaseSettings):
    """Agent role configuration for multi-agent coordination."""

    name: str = ""
    description: str = ""
    model: str = ""
    system_prompt: str | None = None
    tools: list[str] = Field(default_factory=list)


class MultiAgentSettings(BaseSettings):
    """Multi-agent coordination configuration."""

    enabled: bool = False
    max_total_iterations: int = 100
    roles: list[AgentRoleConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# P2A Settings models
# ---------------------------------------------------------------------------


class GatewaySettings(BaseSettings):
    """API Gateway configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    shutdown_timeout: int = 30
    reload_interval: int = 5


class ObservabilitySettings(BaseSettings):
    """Observability configuration."""

    tracing_enabled: bool = False
    otlp_endpoint: str = "http://localhost:4318"
    otlp_protocol: str = "http/protobuf"
    service_name: str = "smartclaw"
    sample_rate: float = 1.0
    redact_sensitive: bool = True


class SmartClawSettings(BaseSettings):
    """SmartClaw root configuration schema.

    Supports environment variable overrides with SMARTCLAW_ prefix
    and nested delimiter __ (double underscore).

    Examples:
        SMARTCLAW_LOGGING__LEVEL=DEBUG
        SMARTCLAW_AGENT_DEFAULTS__MAX_TOKENS=65536
    """

    model_config = {"env_prefix": "SMARTCLAW_", "env_nested_delimiter": "__"}

    # P0 fields
    agent_defaults: AgentDefaultsSettings = Field(default_factory=AgentDefaultsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    credentials: CredentialSettings = Field(default_factory=CredentialSettings)
    model: ModelConfig = Field(default_factory=ModelConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    # P1 fields
    memory: MemorySettings = Field(default_factory=MemorySettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    sub_agent: SubAgentSettings = Field(default_factory=SubAgentSettings)
    multi_agent: MultiAgentSettings = Field(default_factory=MultiAgentSettings)

    # P2A fields
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
