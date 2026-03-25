"""SmartClaw MCP Protocol integration.

Public API:
- MCPConfig, MCPServerConfig — Pydantic configuration models
- MCPManager — MCP server lifecycle manager
- MCPError, MCPInitializationError, MCPTransportError — exception hierarchy
"""

from smartclaw.mcp.config import (
    MCPConfig,
    MCPError,
    MCPInitializationError,
    MCPServerConfig,
    MCPTransportError,
)

__all__ = [
    "MCPConfig",
    "MCPError",
    "MCPInitializationError",
    "MCPServerConfig",
    "MCPTransportError",
]
