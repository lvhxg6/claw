"""Unit tests for MCP config models."""

from __future__ import annotations

from smartclaw.mcp.config import (
    MCPConfig,
    MCPError,
    MCPInitializationError,
    MCPServerConfig,
    MCPTransportError,
)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_mcp_config_defaults() -> None:
    """MCPConfig defaults: enabled=False, servers={}."""
    cfg = MCPConfig()
    assert cfg.enabled is False
    assert cfg.servers == {}


def test_mcp_server_config_defaults() -> None:
    """MCPServerConfig defaults: enabled=True, type=None, etc."""
    cfg = MCPServerConfig()
    assert cfg.enabled is True
    assert cfg.type is None
    assert cfg.command is None
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.env_file is None
    assert cfg.url is None
    assert cfg.headers == {}


def test_mcp_config_with_servers() -> None:
    """MCPConfig can hold named server configs."""
    cfg = MCPConfig(
        enabled=True,
        servers={
            "test_server": MCPServerConfig(command="npx", args=["-y", "test-server"]),
        },
    )
    assert cfg.enabled is True
    assert "test_server" in cfg.servers
    assert cfg.servers["test_server"].command == "npx"
    assert cfg.servers["test_server"].args == ["-y", "test-server"]


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy() -> None:
    """MCPInitializationError and MCPTransportError are subclasses of MCPError."""
    assert issubclass(MCPInitializationError, MCPError)
    assert issubclass(MCPTransportError, MCPError)
    assert issubclass(MCPError, Exception)


def test_exception_messages() -> None:
    """Exceptions carry messages."""
    e = MCPInitializationError("all failed")
    assert str(e) == "all failed"

    e2 = MCPTransportError("connection refused")
    assert str(e2) == "connection refused"


# ---------------------------------------------------------------------------
# SmartClawSettings integration
# ---------------------------------------------------------------------------


def test_smartclaw_settings_has_mcp_field() -> None:
    """SmartClawSettings includes mcp field with MCPConfig default."""
    from smartclaw.config.settings import SmartClawSettings

    settings = SmartClawSettings()
    assert hasattr(settings, "mcp")
    assert isinstance(settings.mcp, MCPConfig)
    assert settings.mcp.enabled is False


def test_smartclaw_settings_env_override(monkeypatch: object) -> None:
    """SmartClawSettings supports SMARTCLAW_MCP__ENABLED env var."""
    import os

    os.environ["SMARTCLAW_MCP__ENABLED"] = "true"
    try:
        from smartclaw.config.settings import SmartClawSettings

        settings = SmartClawSettings()
        assert settings.mcp.enabled is True
    finally:
        os.environ.pop("SMARTCLAW_MCP__ENABLED", None)
