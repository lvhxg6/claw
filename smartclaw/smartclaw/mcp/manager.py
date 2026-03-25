"""MCP Manager — lifecycle management for MCP server connections.

Provides:
- ``detect_transport`` — auto-detect transport type from config
- ``MCPManager`` — connect, discover tools, call tools, close
- ``ServerConnection`` — internal dataclass for connection state
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from mcp import ClientSession
from mcp import types as mcp_types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from smartclaw.mcp.config import (
    MCPConfig,
    MCPInitializationError,
    MCPServerConfig,
    MCPTransportError,
)

logger = structlog.get_logger(component="mcp.manager")


# ---------------------------------------------------------------------------
# Transport detection
# ---------------------------------------------------------------------------


def detect_transport(config: MCPServerConfig) -> Literal["stdio", "http"]:
    """Detect the transport type for an MCP server config.

    Priority:
    1. Explicit ``type`` field (map "sse" → "http")
    2. ``url`` present → "http"
    3. ``command`` present → "stdio"
    4. Neither → raise ValueError
    """
    if config.type is not None:
        t = config.type.lower()
        if t in ("http", "sse"):
            return "http"
        if t == "stdio":
            return "stdio"
        # Treat unknown explicit types as-is if they match known values
        raise ValueError(f"Unknown transport type: {config.type!r}")

    if config.url is not None:
        return "http"

    if config.command is not None:
        return "stdio"

    raise ValueError("MCPServerConfig has neither 'url' nor 'command'; cannot detect transport")


# ---------------------------------------------------------------------------
# ServerConnection dataclass
# ---------------------------------------------------------------------------


@dataclass
class ServerConnection:
    """Internal state for a single connected MCP server."""

    name: str
    session: ClientSession
    tools: list[mcp_types.Tool] = field(default_factory=list)
    _client_cm: AbstractAsyncContextManager[Any] | None = field(default=None, repr=False)
    _session_cm: AbstractAsyncContextManager[Any] | None = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Environment merging helper
# ---------------------------------------------------------------------------


def _merge_env(
    config: MCPServerConfig,
) -> dict[str, str]:
    """Build subprocess environment: parent env < env_file < env mapping."""
    result = dict(os.environ)

    if config.env_file is not None:
        path = config.env_file
        if not os.path.isfile(path):
            raise FileNotFoundError(f"env_file not found: {path}")
        from dotenv import dotenv_values

        file_vars = dotenv_values(path)
        for k, v in file_vars.items():
            if v is not None:
                result[k] = v

    result.update(config.env)
    return result


# ---------------------------------------------------------------------------
# MCPManager
# ---------------------------------------------------------------------------


class MCPManager:
    """Central component managing MCP server connections and tool invocation."""

    def __init__(self) -> None:
        self._servers: dict[str, ServerConnection] = {}
        self._closed: bool = False
        self._in_flight: int = 0
        self._in_flight_zero: asyncio.Event = asyncio.Event()
        self._in_flight_zero.set()  # starts at zero
        self._lock: asyncio.Lock = asyncio.Lock()

    # -- public queries --

    def get_connected_servers(self) -> list[str]:
        """Return names of all currently connected servers."""
        return list(self._servers.keys())

    def get_all_tools(self) -> dict[str, list[mcp_types.Tool]]:
        """Return discovered tools grouped by server name."""
        return {name: list(conn.tools) for name, conn in self._servers.items()}

    # -- lifecycle --

    async def initialize(self, config: MCPConfig) -> None:
        """Connect to all enabled MCP servers concurrently."""
        if not config.enabled:
            return

        enabled = {
            name: srv for name, srv in config.servers.items() if srv.enabled
        }
        if not enabled:
            return

        results = await asyncio.gather(
            *(self._connect_server(name, srv) for name, srv in enabled.items()),
            return_exceptions=True,
        )

        failures: list[str] = []
        for name, result in zip(enabled.keys(), results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("mcp_server_connect_failed", server=name, error=str(result))
                failures.append(f"{name}: {result}")
            elif isinstance(result, ServerConnection):
                self._servers[name] = result
                logger.info("mcp_server_connected", server=name, tools=len(result.tools))

        if len(failures) == len(enabled):
            raise MCPInitializationError(
                f"All enabled MCP servers failed to connect: {'; '.join(failures)}"
            )

    async def _connect_server(self, name: str, config: MCPServerConfig) -> ServerConnection:
        """Connect to a single MCP server and discover its tools."""
        transport = detect_transport(config)

        if transport == "stdio":
            env = _merge_env(config)
            params = StdioServerParameters(
                command=config.command,  # type: ignore[arg-type]
                args=config.args,
                env=env,
            )
            client_cm = stdio_client(params)
        else:
            # streamable HTTP
            client_cm = streamablehttp_client(
                url=config.url,  # type: ignore[arg-type]
                headers=config.headers if config.headers else None,
            )

        try:
            streams = await client_cm.__aenter__()
            # Both stdio_client and streamablehttp_client yield tuples
            # where first two elements are (read_stream, write_stream)
            read_stream, write_stream = streams[0], streams[1]

            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            await session.initialize()

            # Discover tools
            tools_result = await session.list_tools()
            tools = tools_result.tools if tools_result.tools else []

            return ServerConnection(
                name=name,
                session=session,
                tools=tools,
                _client_cm=client_cm,
                _session_cm=session_cm,
            )
        except Exception as e:
            # Try to clean up on failure
            with contextlib.suppress(Exception):
                await client_cm.__aexit__(None, None, None)
            raise MCPTransportError(f"Failed to connect to MCP server '{name}': {e}") from e

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on a connected MCP server.

        Returns the result as a string. Never raises to the Agent Graph.
        """
        if self._closed:
            return "Error: MCP manager is closed"

        if server_name not in self._servers:
            return f"Error: MCP server '{server_name}' not found"

        conn = self._servers[server_name]

        # Increment in-flight counter
        async with self._lock:
            self._in_flight += 1
            self._in_flight_zero.clear()

        try:
            result = await conn.session.call_tool(tool_name, arguments)

            # Extract text content
            parts: list[str] = []
            if result.content:
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)

            text = "\n".join(parts) if parts else ""

            if result.isError:
                return text if text else f"Error: Tool '{tool_name}' returned an error"

            return text
        except Exception as e:
            logger.error("mcp_call_tool_error", server=server_name, tool=tool_name, error=str(e))
            return f"Error: {e}"
        finally:
            async with self._lock:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._in_flight_zero.set()

    async def close(self) -> None:
        """Drain in-flight calls and close all server sessions."""
        self._closed = True

        # Wait for in-flight calls to complete
        await self._in_flight_zero.wait()

        # Close all sessions
        for name, conn in self._servers.items():
            try:
                if conn._session_cm is not None:
                    await conn._session_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("mcp_session_close_error", server=name, error=str(e))
            try:
                if conn._client_cm is not None:
                    await conn._client_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("mcp_client_close_error", server=name, error=str(e))

        self._servers.clear()
