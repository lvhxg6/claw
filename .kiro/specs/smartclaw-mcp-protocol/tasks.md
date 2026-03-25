# Implementation Plan: SmartClaw MCP Protocol Integration

## Overview

Implement MCP Protocol integration (Spec: smartclaw-mcp-protocol) for SmartClaw. This adds three new modules — `smartclaw/mcp/config.py` (Pydantic config models), `smartclaw/mcp/manager.py` (MCP Manager), and `smartclaw/tools/mcp_tool.py` (MCP Tool Bridge) — plus custom exceptions, and wires MCP tools into the existing Agent Graph and ToolRegistry.

All new code lives under `smartclaw/smartclaw/mcp/` and `smartclaw/smartclaw/tools/mcp_tool.py`, with tests under `smartclaw/tests/mcp/`. The `mcp>=2.1` dependency must be added to `pyproject.toml`.

## Tasks

- [x] 1. Project scaffolding and MCP config models
  - [x] 1.1 Add `mcp>=2.1` to `pyproject.toml` dependencies and create `smartclaw/smartclaw/mcp/__init__.py`
    - Add `mcp>=2.1` to `[project.dependencies]`
    - Create `smartclaw/smartclaw/mcp/__init__.py` exporting public names
    - Create `smartclaw/tests/mcp/__init__.py` test package
    - _Requirements: 7.1_

  - [x] 1.2 Implement `MCPServerConfig` and `MCPConfig` in `smartclaw/smartclaw/mcp/config.py`
    - Implement `MCPServerConfig(BaseModel)` with fields: `enabled`, `type`, `command`, `args`, `env`, `env_file`, `url`, `headers` (see design §1–§2)
    - Implement `MCPConfig(BaseModel)` with fields: `enabled` (default `False`), `servers` (default `{}`)
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [x] 1.3 Integrate `MCPConfig` into `SmartClawSettings`
    - Add `mcp: MCPConfig = Field(default_factory=MCPConfig)` to `SmartClawSettings` in `smartclaw/smartclaw/config/settings.py`
    - Supports env var overrides with `SMARTCLAW_MCP__` prefix
    - _Requirements: 7.1, 7.6_

  - [x] 1.4 Implement exception hierarchy in `smartclaw/smartclaw/mcp/config.py`
    - Implement `MCPError(Exception)`, `MCPInitializationError(MCPError)`, `MCPTransportError(MCPError)`
    - _Requirements: 1.3, 9.1_

  - [x] 1.5 Write property test for Pydantic validation rejects invalid types
    - **Property 12: Pydantic validation rejects invalid types**
    - For any input dict containing a field with an invalid type for `MCPConfig` or `MCPServerConfig`, Pydantic model construction shall raise `ValidationError`
    - File: `smartclaw/tests/mcp/test_config_props.py`
    - **Validates: Requirements 7.5**

  - [x] 1.6 Write unit tests for MCP config models
    - Test default values: `MCPConfig.enabled` is `False`, `MCPConfig.servers` is `{}`, `MCPServerConfig.enabled` is `True`
    - Test env var override via `SmartClawSettings` with `SMARTCLAW_MCP__ENABLED`
    - Test validation error when neither `url` nor `command` is provided (covered by transport detection, but config-level test)
    - File: `smartclaw/tests/mcp/test_config.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_

- [x] 2. Transport detection and MCP Manager core
  - [x] 2.1 Implement `detect_transport()` function in `smartclaw/smartclaw/mcp/manager.py`
    - If `type` is explicitly set → use it (map "sse" to "http")
    - If `url` is present and no `type` → return "http"
    - If `command` is present, no `url`, no `type` → return "stdio"
    - If neither `url` nor `command` → raise `ValueError`
    - _Requirements: 2.1, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4_

  - [x] 2.2 Write property test for transport detection correctness
    - **Property 1: Transport detection correctness**
    - For any `MCPServerConfig`, `detect_transport()` returns the correct transport type following the priority rules; raises `ValueError` when neither `url` nor `command` is present
    - File: `smartclaw/tests/mcp/test_transport_detection_props.py`
    - **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**

  - [x] 2.3 Implement `ServerConnection` dataclass and `MCPManager` class skeleton in `smartclaw/smartclaw/mcp/manager.py`
    - Implement `ServerConnection` dataclass with `name`, `session`, `tools`, `_client_cm`, `_session_cm`
    - Implement `MCPManager` with internal state: `_servers`, `_closed`, `_in_flight`, `_in_flight_zero`, `_lock`
    - Implement `get_connected_servers()` and `get_all_tools()` methods
    - _Requirements: 1.7, 5.1, 5.2, 5.3, 5.4_

  - [x] 2.4 Implement `MCPManager.initialize()` — connect to all enabled servers concurrently
    - Implement `_connect_server()` internal method: detect transport, create client (stdio or streamable HTTP), initialize session, discover tools via `session.list_tools()`
    - Handle env_file loading with `python-dotenv` and merge precedence: parent env < env_file < env mapping
    - Use `asyncio.gather(return_exceptions=True)` for concurrent connection
    - Skip disabled servers; log warnings for failed servers; raise `MCPInitializationError` if all enabled servers fail
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.3, 3.4, 5.1, 5.2, 5.4, 9.5_

  - [x] 2.5 Implement `MCPManager.call_tool()` — delegate tool calls with in-flight tracking
    - Check closed flag → return error string if closed
    - Check server exists → return error string if not found
    - Increment in-flight counter, call `session.call_tool()`, decrement counter, signal event when zero
    - Extract text content from result, handle `is_error` flag
    - _Requirements: 6.7, 6.8, 6.9, 9.2, 9.3, 9.4_

  - [x] 2.6 Implement `MCPManager.close()` — drain in-flight calls and close all sessions
    - Set closed flag, wait for in-flight counter to reach zero, close all sessions via context managers
    - _Requirements: 1.5, 1.6_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. MCP Manager property and unit tests
  - [x] 4.1 Write property test for initialization connects exactly enabled and successful servers
    - **Property 2: Initialization connects exactly the enabled and successful servers**
    - For any `MCPConfig` with a mix of enabled/disabled servers where some succeed and some fail, `get_connected_servers()` returns exactly the enabled-and-successful set
    - File: `smartclaw/tests/mcp/test_manager_props.py`
    - **Validates: Requirements 1.1, 1.2, 1.4, 1.7**

  - [x] 4.2 Write property test for close releases all sessions
    - **Property 3: Close releases all sessions**
    - For any `MCPManager` with one or more connected servers, calling `close()` closes every active session, leaving zero open sessions
    - File: `smartclaw/tests/mcp/test_manager_props.py`
    - **Validates: Requirements 1.5**

  - [x] 4.3 Write property test for close prevents new tool calls
    - **Property 4: Close prevents new tool calls**
    - For any `MCPManager` that has been closed, every subsequent `call_tool()` returns an error string (not an unhandled exception)
    - File: `smartclaw/tests/mcp/test_manager_props.py`
    - **Validates: Requirements 9.4**

  - [x] 4.4 Write property test for tool discovery grouping
    - **Property 11: Tool discovery grouping**
    - For any set of connected MCP servers, `get_all_tools()` returns a mapping where each key is a connected server name and each value is the complete list of tools advertised by that server
    - File: `smartclaw/tests/mcp/test_manager_props.py`
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [x] 4.5 Write property test for environment variable merge precedence
    - **Property 10: Environment variable merge precedence**
    - For any combination of parent env, env_file contents, and `env` mapping, the resulting subprocess environment reflects: parent env < env_file < env mapping
    - File: `smartclaw/tests/mcp/test_env_merge_props.py`
    - **Validates: Requirements 2.4, 2.5**

  - [x] 4.6 Write unit tests for MCPManager
    - Test connect/close happy path lifecycle
    - Test all-fail raises `MCPInitializationError` with aggregated reasons (Req 1.3)
    - Test in-flight wait on close (Req 1.6)
    - Test subprocess crash marks server as disconnected (Req 9.1)
    - Test call to unknown server returns error string (Req 9.3)
    - Test call to disconnected server returns error string (Req 9.2)
    - Test missing env_file raises `FileNotFoundError` (Req 9.5)
    - Test stdio args/env passthrough (Req 2.2, 2.3)
    - Test HTTP headers passthrough (Req 3.3)
    - File: `smartclaw/tests/mcp/test_manager.py`
    - _Requirements: 1.3, 1.6, 2.2, 2.3, 3.3, 9.1, 9.2, 9.3, 9.5_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. MCP Tool Bridge
  - [x] 6.1 Implement tool name sanitization logic in `smartclaw/smartclaw/tools/mcp_tool.py`
    - Lowercase, replace disallowed chars (not `[a-z0-9_-]`) with `_`, collapse consecutive `_`, trim leading/trailing `_`
    - Prefix with `mcp_`, cap at 64 chars, append `_` + 8-char FNV-1a hash when sanitization is lossy or name exceeds limit
    - _Requirements: 6.2, 6.3_

  - [x] 6.2 Implement JSON Schema to Pydantic BaseModel conversion in `smartclaw/smartclaw/tools/mcp_tool.py`
    - Convert MCP tool `inputSchema` (JSON Schema dict) to a dynamic Pydantic `BaseModel` via `pydantic.create_model()`
    - Map JSON Schema `type` field to Python types; fall back to `dict[str, Any]` args_schema on failure
    - _Requirements: 6.6_

  - [x] 6.3 Implement `MCPToolBridge(BaseTool)` class in `smartclaw/smartclaw/tools/mcp_tool.py`
    - Store original server name and tool name for delegation
    - `_arun()`: call `MCPManager.call_tool()` with original names and exact arguments
    - `_run()`: raise `NotImplementedError("Use async")`
    - Set description to `"[MCP:{server_name}] {tool_description}"`, fallback to `"[MCP:{server_name}] MCP tool from {server_name} server"` when empty
    - _Requirements: 6.1, 6.4, 6.5, 6.7, 6.8, 6.9, 6.10_

  - [x] 6.4 Implement `create_mcp_tools()` factory function in `smartclaw/smartclaw/tools/mcp_tool.py`
    - Iterate `manager.get_all_tools()`, create one `MCPToolBridge` per tool, return flat list
    - _Requirements: 6.1_

  - [x] 6.5 Write property test for tool name sanitization invariants
    - **Property 5: Tool name sanitization invariants**
    - For any server name and tool name strings, the sanitized name: (a) matches `^[a-z0-9_-]+$`, (b) is at most 64 chars, (c) starts with `mcp_`, (d) distinct input pairs produce distinct outputs
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.2, 6.3**

  - [x] 6.6 Write property test for tool description format
    - **Property 6: Tool description format**
    - For any MCP tool with non-empty description, bridge description equals `"[MCP:{server_name}] {tool_description}"`; for empty/missing description, equals `"[MCP:{server_name}] MCP tool from {server_name} server"`
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.4, 6.5**

  - [x] 6.7 Write property test for tool bridge creation count
    - **Property 7: Tool bridge creation count**
    - For any `MCPManager` with discovered tools, `create_mcp_tools()` returns exactly one `BaseTool` per discovered MCP tool across all connected servers
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.1**

  - [x] 6.8 Write property test for tool call delegation correctness
    - **Property 8: Tool call delegation correctness**
    - For any `MCPToolBridge` instance, `_arun()` invokes `MCPManager.call_tool()` with the original (unsanitized) server name, original tool name, and exact arguments
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.7**

  - [x] 6.9 Write property test for text content extraction
    - **Property 9: Text content extraction**
    - For any list of MCP text content parts, the bridge returns text values joined by newline characters
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.9**

  - [x] 6.10 Write property test for schema conversion produces BaseModel
    - **Property 14: Schema conversion produces BaseModel**
    - For any MCP tool input schema (valid JSON Schema dict), the bridge produces an `args_schema` that is a subclass of Pydantic `BaseModel`
    - File: `smartclaw/tests/mcp/test_tool_bridge_props.py`
    - **Validates: Requirements 6.6**

  - [x] 6.11 Write unit tests for MCPToolBridge
    - Test error result handling (`is_error` flag) returns error text (Req 6.8)
    - Test exception catching returns `"Error: {message}"` (Req 6.10)
    - Test no-description fallback text (Req 6.5)
    - Test disconnected server call returns error string (Req 9.2)
    - Test unknown server call returns error string (Req 9.3)
    - File: `smartclaw/tests/mcp/test_tool_bridge.py`
    - _Requirements: 6.5, 6.8, 6.10, 9.2, 9.3_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Agent Graph integration and wiring
  - [x] 8.1 Extend `create_all_tools()` in `smartclaw/smartclaw/agent/graph.py` to accept optional `MCPManager`
    - Add `mcp_manager: MCPManager | None = None` parameter
    - When `mcp_manager` is provided, call `create_mcp_tools(manager)` and merge into `ToolRegistry`
    - When `mcp_manager` is `None`, skip MCP tool registration (existing behavior preserved)
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 8.2 Write property test for registry merge includes all tool sources
    - **Property 13: Registry merge includes all tool sources**
    - For any combination of browser tools, system tools, and MCP tools passed to `create_all_tools()`, the resulting registry contains every tool from all three sources
    - File: `smartclaw/tests/mcp/test_integration_props.py`
    - **Validates: Requirements 8.1, 8.2**

  - [x] 8.3 Write unit tests for Agent Graph integration
    - Test MCP disabled skips registration (Req 8.3)
    - Test duplicate tool name replacement and warning log (Req 8.4)
    - Test combined browser + system + MCP tools produce valid `list[BaseTool]`
    - File: `smartclaw/tests/mcp/test_integration.py`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- Each property test must run at least 100 iterations (`@settings(max_examples=100)`)
- Each property test must include the annotation comment: `# Feature: smartclaw-mcp-protocol, Property {N}: {title}`
- All 14 correctness properties from the design are covered as required property test tasks
- All 9 requirements (1.1–9.5) are covered by implementation and test tasks
- Property tests use Hypothesis with mock `ClientSession` objects to avoid real subprocess/HTTP connections
- Unit tests use `pytest-asyncio` for async test support and `AsyncMock` for mocking MCP SDK internals
- The `mcp` Python SDK (>=2.1) provides `StdioServerParameters`, `streamablehttp_client()`, and `ClientSession`
