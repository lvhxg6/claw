"""MCP configuration models and exception hierarchy.

Provides Pydantic models for MCP server configuration and custom exceptions
for MCP-related errors.
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class MCPError(Exception):
    """Base exception for MCP integration errors."""


class MCPInitializationError(MCPError):
    """Raised when all enabled MCP servers fail to connect."""


class MCPTransportError(MCPError):
    """Raised when transport detection or connection fails for a single server."""


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server entry."""

    enabled: bool = True
    type: str | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    env_file: str | None = None
    url: str | None = None
    headers: dict[str, str] = {}


class MCPConfig(BaseModel):
    """Top-level MCP configuration section."""

    enabled: bool = False
    servers: dict[str, MCPServerConfig] = {}
