"""Pydantic Settings schema definitions for SmartClaw configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings

from smartclaw.browser.engine import BrowserConfig
from smartclaw.mcp.config import MCPConfig
from smartclaw.providers.config import ModelConfig, ProviderSpec


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
    # L1: ToolResultGuard
    tool_result_max_chars: int = 30000
    tool_result_head_chars: int = 12000
    tool_result_tail_chars: int = 8000
    tool_overrides: dict[str, dict[str, int]] = Field(default_factory=dict)
    # L2: SessionPruner
    soft_trim_threshold: float = 0.5
    hard_clear_threshold: float = 0.7
    pruner_keep_recent: int = 5
    pruner_keep_head: int = 2
    tool_allow_list: list[str] = Field(default_factory=list)
    tool_deny_list: list[str] = Field(default_factory=list)
    # L4: Multi-stage compaction
    chunk_max_tokens: int = 4000
    part_max_tokens: int = 2000

    # Memory enhancement: MEMORY.md and memory/ directory support
    memory_file_enabled: bool = Field(default=True, description="Enable MEMORY.md loading")
    memory_dir_enabled: bool = Field(default=True, description="Enable memory/ directory indexing")
    chunk_tokens: int = Field(default=512, description="Chunk size in tokens")
    chunk_overlap: int = Field(default=64, description="Chunk overlap in tokens")
    max_file_size: int = Field(default=2 * 1024 * 1024, description="Max single file size (2MB)")
    max_dir_size: int = Field(default=50 * 1024 * 1024, description="Max directory total size (50MB)")

    # Vector search configuration
    embedding_provider: str = Field(default="auto", description="Embedding provider: auto | openai | ollama | none")
    vector_weight: float = Field(default=0.7, description="Vector search weight")
    text_weight: float = Field(default=0.3, description="BM25 search weight")
    top_k: int = Field(default=5, description="Number of results to return")

    # Fact extraction configuration
    auto_extract: bool = Field(default=False, description="Enable automatic fact extraction")
    max_facts: int = Field(default=100, description="Maximum number of facts to store")
    fact_confidence_threshold: float = Field(default=0.7, description="Fact confidence threshold")


class SkillsSettings(BaseSettings):
    """Skills module configuration."""

    enabled: bool = True
    workspace_dir: str = "{workspace}/skills"
    global_dir: str = "~/.smartclaw/skills"

    # Hot reload configuration
    hot_reload: bool = Field(default=True, description="Enable skills hot reload")
    debounce_ms: int = Field(default=250, description="Debounce time in milliseconds")


class BootstrapSettings(BaseSettings):
    """Bootstrap module configuration for SOUL.md, USER.md, TOOLS.md files."""

    enabled: bool = Field(default=True, description="Enable bootstrap files loading")
    max_file_size: int = Field(default=512 * 1024, description="Max single file size (512KB)")


class ConfigSettings(BaseSettings):
    """Config module configuration for hot reload."""

    hot_reload: bool = Field(default=True, description="Enable config hot reload")
    debounce_ms: int = Field(default=500, description="Debounce time in milliseconds")


class CapabilityPackSettings(BaseSettings):
    """Capability pack configuration."""

    enabled: bool = Field(default=True, description="Enable capability pack loading")
    workspace_dir: str = "{workspace}/capability_packs"
    global_dir: str = "~/.smartclaw/capability_packs"


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


class OrchestratorSettings(BaseSettings):
    """Execution mode and orchestration settings."""

    enabled: bool = True
    mode: str = Field(default="auto", description="Execution mode: auto | classic | orchestrator")
    plan_enabled: bool = Field(default=True, description="Enable explicit planning when orchestrator mode is active")
    max_concurrent_workers: int = Field(default=4, description="Global concurrent worker cap")
    max_batch_size: int = Field(default=4, description="Maximum tasks per dispatch batch")
    max_phases: int = Field(default=8, description="Maximum orchestration phases")
    enable_explicit_compaction: bool = Field(
        default=True,
        description="Allow explicit context compaction between phases",
    )
    enable_dispatch_policy: bool = Field(default=True, description="Enable dispatch policy checks")


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
    providers: list[ProviderSpec] = Field(
        default_factory=list,
        description="Custom ProviderSpec list for config-driven provider registration",
    )

    # P1 fields
    memory: MemorySettings = Field(default_factory=MemorySettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    bootstrap: BootstrapSettings = Field(default_factory=BootstrapSettings)
    config: ConfigSettings = Field(default_factory=ConfigSettings)
    capability_packs: CapabilityPackSettings = Field(default_factory=CapabilityPackSettings)
    sub_agent: SubAgentSettings = Field(default_factory=SubAgentSettings)
    multi_agent: MultiAgentSettings = Field(default_factory=MultiAgentSettings)

    # P2A fields
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)

    # L5 ContextEngine
    context_engine: str = Field(
        default="legacy",
        description="Context engine name (registered in ContextEngineRegistry). Default: 'legacy'",
    )
