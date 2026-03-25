# Requirements Document

## Introduction

SmartClaw MCP Protocol integration enables SmartClaw to connect to external MCP (Model Context Protocol) servers, discover their tools, and expose those tools as LangChain BaseTool instances within the existing Agent Graph. This is the final P0 spec, completing the core MVP by bridging the MCP tool ecosystem into SmartClaw's tool pipeline.

The implementation covers: an MCP Manager for multi-server lifecycle management, stdio and Streamable HTTP transports, MCP-to-LangChain tool bridging, YAML-based MCP server configuration integrated with Pydantic Settings, and registration of MCP tools into the existing ToolRegistry.

## Glossary

- **MCP_Manager**: The central component that manages connections to one or more MCP servers, handling startup, shutdown, reconnection, and tool discovery.
- **MCP_Server**: An external process or remote service that implements the Model Context Protocol and exposes tools, resources, or prompts.
- **MCP_Tool_Bridge**: The adapter layer that converts an MCP server tool definition into a LangChain BaseTool instance usable by the Agent Graph.
- **Stdio_Transport**: A transport mechanism where the MCP_Manager launches an MCP_Server as a child subprocess and communicates via stdin/stdout using JSON-RPC.
- **Streamable_HTTP_Transport**: A transport mechanism where the MCP_Manager connects to a remote MCP_Server over HTTP using the MCP Streamable HTTP protocol.
- **ToolRegistry**: The existing SmartClaw central registry (smartclaw/tools/registry.py) that holds all BaseTool instances for the Agent Graph.
- **Agent_Graph**: The existing LangGraph StateGraph (smartclaw/agent/graph.py) that orchestrates the ReAct reasoning-action loop.
- **SmartClawSettings**: The existing Pydantic Settings root configuration class (smartclaw/config/settings.py).
- **MCP_Server_Config**: A Pydantic model representing the configuration for a single MCP server (command, args, env, type, enabled, url, headers).
- **MCP_Config**: A Pydantic model representing the top-level MCP configuration section containing enabled flag and a mapping of server names to MCP_Server_Config entries.

## Requirements

### Requirement 1: MCP Manager Lifecycle

**User Story:** As a developer, I want the MCP_Manager to manage the full lifecycle of MCP server connections, so that MCP servers are started, connected, and stopped reliably.

#### Acceptance Criteria

1. WHEN the MCP_Manager is initialized with an MCP_Config, THE MCP_Manager SHALL connect to all enabled MCP_Server entries concurrently.
2. WHEN an MCP_Server has its enabled field set to false, THE MCP_Manager SHALL skip that server during initialization.
3. WHEN all enabled MCP_Server connections fail during initialization, THE MCP_Manager SHALL raise an error containing all individual failure reasons.
4. WHEN some but not all enabled MCP_Server connections fail during initialization, THE MCP_Manager SHALL log warnings for failed servers and continue operating with the successfully connected servers.
5. WHEN the MCP_Manager close method is called, THE MCP_Manager SHALL close all active MCP_Server sessions and release all associated resources.
6. WHEN the MCP_Manager close method is called while tool calls are in flight, THE MCP_Manager SHALL wait for in-flight tool calls to complete before closing sessions.
7. THE MCP_Manager SHALL provide a method to retrieve all currently connected MCP_Server names.

### Requirement 2: Stdio Transport

**User Story:** As a developer, I want the MCP_Manager to launch MCP servers as subprocesses using stdio transport, so that I can use locally installed MCP server packages.

#### Acceptance Criteria

1. WHEN an MCP_Server_Config specifies a command field and no url field, THE MCP_Manager SHALL use stdio transport to launch the server as a subprocess.
2. WHEN using stdio transport, THE MCP_Manager SHALL pass the configured args list as command-line arguments to the subprocess.
3. WHEN using stdio transport, THE MCP_Manager SHALL set environment variables on the subprocess from the MCP_Server_Config env mapping.
4. WHEN using stdio transport and an env_file path is configured, THE MCP_Manager SHALL load environment variables from the specified file and merge them with the env mapping, where env mapping values take precedence.
5. WHEN using stdio transport, THE MCP_Manager SHALL inherit the parent process environment variables as the base, with env_file and env mapping overriding in that order.
6. IF the stdio subprocess fails to start, THEN THE MCP_Manager SHALL return an error identifying the server name and the failure reason.

### Requirement 3: Streamable HTTP Transport

**User Story:** As a developer, I want the MCP_Manager to connect to remote MCP servers over HTTP, so that I can use cloud-hosted MCP services.

#### Acceptance Criteria

1. WHEN an MCP_Server_Config specifies a url field, THE MCP_Manager SHALL use Streamable HTTP transport to connect to the remote server.
2. WHEN an MCP_Server_Config specifies a type field of "http" or "sse", THE MCP_Manager SHALL use Streamable HTTP transport regardless of other fields.
3. WHEN using Streamable HTTP transport and the MCP_Server_Config includes a headers mapping, THE MCP_Manager SHALL include those headers in all HTTP requests to the server.
4. IF the HTTP connection to a remote MCP_Server fails, THEN THE MCP_Manager SHALL return an error identifying the server name and the failure reason.

### Requirement 4: Transport Auto-Detection

**User Story:** As a developer, I want the MCP_Manager to automatically detect the correct transport type, so that I do not need to explicitly specify it in simple configurations.

#### Acceptance Criteria

1. WHEN an MCP_Server_Config has a url field and no type field, THE MCP_Manager SHALL auto-detect Streamable HTTP transport.
2. WHEN an MCP_Server_Config has a command field, no url field, and no type field, THE MCP_Manager SHALL auto-detect stdio transport.
3. WHEN an MCP_Server_Config specifies a type field, THE MCP_Manager SHALL use the specified transport type regardless of auto-detection.
4. IF an MCP_Server_Config has neither a url field nor a command field, THEN THE MCP_Manager SHALL return a validation error for that server entry.

### Requirement 5: Tool Discovery

**User Story:** As a developer, I want the MCP_Manager to discover tools from connected MCP servers, so that those tools can be made available to the Agent.

#### Acceptance Criteria

1. WHEN the MCP_Manager successfully connects to an MCP_Server, THE MCP_Manager SHALL list all tools advertised by that server.
2. THE MCP_Manager SHALL store discovered tools associated with their originating server name.
3. THE MCP_Manager SHALL provide a method to retrieve all discovered tools grouped by server name.
4. WHEN an MCP_Server does not advertise tool capabilities, THE MCP_Manager SHALL record an empty tool list for that server.

### Requirement 6: MCP Tool Bridging

**User Story:** As a developer, I want each MCP tool to be wrapped as a LangChain BaseTool, so that MCP tools integrate seamlessly with the existing Agent Graph and ToolRegistry.

#### Acceptance Criteria

1. THE MCP_Tool_Bridge SHALL create a LangChain BaseTool instance for each discovered MCP tool.
2. THE MCP_Tool_Bridge SHALL set the BaseTool name to a sanitized identifier in the format "mcp_{server_name}_{tool_name}", lowercased, with disallowed characters replaced by underscores.
3. THE MCP_Tool_Bridge SHALL cap the BaseTool name at 64 characters total, appending a hash suffix when sanitization is lossy or the name exceeds the limit.
4. THE MCP_Tool_Bridge SHALL set the BaseTool description to "[MCP:{server_name}] {tool_description}", using the server name as a prefix.
5. WHEN an MCP tool has no description, THE MCP_Tool_Bridge SHALL use "MCP tool from {server_name} server" as the fallback description.
6. THE MCP_Tool_Bridge SHALL convert the MCP tool input schema into a Pydantic BaseModel for the BaseTool args_schema field.
7. WHEN the BaseTool is invoked with arguments, THE MCP_Tool_Bridge SHALL call the MCP_Manager CallTool method with the correct server name, tool name, and arguments.
8. WHEN the MCP_Server returns an error result (is_error flag set), THE MCP_Tool_Bridge SHALL return the error message as a string to the Agent.
9. WHEN the MCP_Server returns text content, THE MCP_Tool_Bridge SHALL extract and concatenate all text content parts separated by newlines.
10. IF the MCP tool call raises an exception, THEN THE MCP_Tool_Bridge SHALL catch the exception, log it, and return an error string to the Agent.

### Requirement 7: MCP Configuration Schema

**User Story:** As a developer, I want to configure MCP servers in the YAML config file, so that I can declaratively manage which MCP servers SmartClaw connects to.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include an mcp field of type MCP_Config.
2. THE MCP_Config SHALL have an enabled boolean field defaulting to false.
3. THE MCP_Config SHALL have a servers field containing a mapping of server names to MCP_Server_Config entries.
4. THE MCP_Server_Config SHALL support the following fields: enabled (bool, default true), type (optional string: "stdio", "http", "sse"), command (optional string), args (optional list of strings), env (optional mapping of string to string), env_file (optional string), url (optional string), headers (optional mapping of string to string).
5. THE MCP_Config SHALL be validated by Pydantic, rejecting invalid field types at configuration load time.
6. THE SmartClawSettings SHALL support environment variable overrides for MCP configuration using the SMARTCLAW_MCP__ prefix.

### Requirement 8: Integration with ToolRegistry and Agent Graph

**User Story:** As a developer, I want MCP tools to be automatically registered in the ToolRegistry alongside browser and system tools, so that the Agent can use all tools uniformly.

#### Acceptance Criteria

1. WHEN MCP is enabled and MCP servers are connected, THE Agent_Graph integration layer SHALL register all MCP bridged tools into the ToolRegistry.
2. THE Agent_Graph integration layer SHALL merge MCP tools with existing browser tools and system tools into a single ToolRegistry.
3. WHEN MCP is disabled in configuration, THE Agent_Graph integration layer SHALL skip MCP tool registration and operate with only browser and system tools.
4. WHEN an MCP tool has the same name as an existing tool in the ToolRegistry, THE ToolRegistry SHALL replace the existing tool and log a warning.

### Requirement 9: Error Handling and Resilience

**User Story:** As a developer, I want the MCP integration to handle errors gracefully, so that individual MCP server failures do not crash the entire Agent.

#### Acceptance Criteria

1. IF an MCP_Server subprocess crashes after initial connection, THEN THE MCP_Manager SHALL log the error and mark the server as disconnected.
2. IF a tool call is made to a disconnected MCP_Server, THEN THE MCP_Tool_Bridge SHALL return an error string indicating the server is unavailable.
3. IF a tool call is made to a server name that does not exist in the MCP_Manager, THEN THE MCP_Tool_Bridge SHALL return an error string indicating the server was not found.
4. WHEN the MCP_Manager is closed, THE MCP_Manager SHALL prevent new tool calls from being accepted and return an error for any subsequent call attempts.
5. IF an env_file path specified in MCP_Server_Config does not exist, THEN THE MCP_Manager SHALL return an error identifying the missing file path.
