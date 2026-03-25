"""MCP Tool Bridge — wraps MCP tools as LangChain BaseTool instances.

Provides:
- ``sanitize_tool_name`` — name sanitization with FNV-1a hash suffix
- ``json_schema_to_model`` — JSON Schema → Pydantic BaseModel conversion
- ``MCPToolBridge`` — BaseTool subclass delegating to MCPManager
- ``create_mcp_tools`` — factory creating all MCP tool bridges
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from langchain_core.tools import BaseTool
from pydantic import BaseModel, create_model

logger = structlog.get_logger(component="tools.mcp_tool")

# Maximum length for sanitized tool names
_MAX_NAME_LEN = 64
# Hash suffix length (8 hex chars)
_HASH_LEN = 8


# ---------------------------------------------------------------------------
# FNV-1a hash (32-bit)
# ---------------------------------------------------------------------------


def _fnv1a_hash(data: str) -> str:
    """Compute FNV-1a 32-bit hash and return as 8-char hex string."""
    h = 0x811C9DC5
    for byte in data.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


# ---------------------------------------------------------------------------
# Tool name sanitization
# ---------------------------------------------------------------------------


def sanitize_tool_name(server_name: str, tool_name: str) -> str:
    """Sanitize server + tool name into a valid tool identifier.

    Rules:
    - Prefix with ``mcp_``
    - Lowercase
    - Replace disallowed chars (not ``[a-z0-9_-]``) with ``_``
    - Collapse consecutive ``_``
    - Trim leading/trailing ``_`` from the body
    - Cap at 64 chars total; append ``_`` + 8-char FNV-1a hash when lossy or over limit
    """
    original = f"{server_name}_{tool_name}"
    raw = f"mcp_{server_name}_{tool_name}".lower()

    # Replace disallowed chars
    sanitized = re.sub(r"[^a-z0-9_\-]", "_", raw)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_{2,}", "_", sanitized)
    # Trim leading/trailing underscores
    sanitized = sanitized.strip("_")

    # Ensure it starts with mcp_
    if not sanitized.startswith("mcp_"):
        sanitized = "mcp_" + sanitized

    # Determine if sanitization was lossy
    lossy = sanitized != raw.lower() or sanitized != f"mcp_{server_name}_{tool_name}".lower()

    if lossy or len(sanitized) > _MAX_NAME_LEN:
        hash_suffix = _fnv1a_hash(original)
        # Truncate to make room for _XXXXXXXX
        max_base = _MAX_NAME_LEN - 1 - _HASH_LEN  # 64 - 1 - 8 = 55
        base = sanitized[:max_base].rstrip("_")
        sanitized = f"{base}_{hash_suffix}"

    # Final safety cap
    if len(sanitized) > _MAX_NAME_LEN:
        sanitized = sanitized[:_MAX_NAME_LEN]

    return sanitized


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic BaseModel conversion
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def json_schema_to_model(schema: dict[str, Any], model_name: str = "MCPToolInput") -> type[BaseModel]:
    """Convert a JSON Schema dict to a dynamic Pydantic BaseModel.

    Falls back to a model with a single ``arguments: dict[str, Any]`` field
    if conversion fails.
    """
    try:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        if not properties:
            # No properties — use generic dict input
            return create_model(model_name, arguments=(dict[str, Any], {}))

        fields: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            json_type = prop_schema.get("type", "string")
            python_type = _JSON_TYPE_MAP.get(json_type, Any)

            if prop_name in required:
                fields[prop_name] = (python_type, ...)
            else:
                fields[prop_name] = (python_type | None, None)

        return create_model(model_name, **fields)
    except Exception:
        logger.warning("json_schema_conversion_failed", schema=schema)
        return create_model(model_name, arguments=(dict[str, Any], {}))


# ---------------------------------------------------------------------------
# MCPToolBridge
# ---------------------------------------------------------------------------


class MCPToolBridge(BaseTool):
    """Wraps a single MCP tool as a LangChain BaseTool."""

    name: str
    description: str
    args_schema: type[BaseModel]

    # Internal fields for delegation (not part of BaseTool interface)
    server_name: str = ""
    original_tool_name: str = ""
    _mcp_manager: Any = None  # MCPManager reference, set post-init

    def _run(self, **kwargs: Any) -> str:
        raise NotImplementedError("Use async")

    async def _arun(self, **kwargs: Any) -> str:
        """Delegate to MCPManager.call_tool with original names."""
        if self._mcp_manager is None:
            return "Error: MCP manager not available"
        try:
            result: str = await self._mcp_manager.call_tool(
                self.server_name,
                self.original_tool_name,
                kwargs,
            )
            return result
        except Exception as e:
            logger.error(
                "mcp_tool_bridge_error",
                server=self.server_name,
                tool=self.original_tool_name,
                error=str(e),
            )
            return f"Error: {e}"


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def create_mcp_tools(manager: Any) -> list[BaseTool]:
    """Create BaseTool instances for all discovered MCP tools.

    Args:
        manager: An MCPManager instance with discovered tools.

    Returns:
        A flat list of MCPToolBridge instances.
    """
    tools: list[BaseTool] = []
    all_server_tools = manager.get_all_tools()

    for server_name, server_tools in all_server_tools.items():
        for mcp_tool in server_tools:
            sanitized_name = sanitize_tool_name(server_name, mcp_tool.name)

            # Build description
            if mcp_tool.description:
                desc = f"[MCP:{server_name}] {mcp_tool.description}"
            else:
                desc = f"[MCP:{server_name}] MCP tool from {server_name} server"

            # Build args schema
            input_schema = mcp_tool.inputSchema if mcp_tool.inputSchema else {}
            args_model = json_schema_to_model(input_schema, model_name=f"{sanitized_name}_input")

            bridge = MCPToolBridge(
                name=sanitized_name,
                description=desc,
                args_schema=args_model,
                server_name=server_name,
                original_tool_name=mcp_tool.name,
            )
            bridge._mcp_manager = manager
            tools.append(bridge)

    return tools
