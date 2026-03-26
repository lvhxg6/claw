# Requirements Document

## Introduction

SmartClaw P2A 生产级服务是 SmartClaw AI Agent 项目 P2 阶段的第一批次开发，在 P0 核心 MVP 和 P1 增强能力全部完成的基础上，新增 3 个生产级服务模块：

1. **API 网关（API Gateway）** — 基于 FastAPI 的 HTTP 服务层，让 SmartClaw 能作为 HTTP 服务运行（不只是 CLI），支持 SSE 流式响应、模块化路由、热重载和优雅关闭
2. **生命周期 Hook（Lifecycle Hooks）** — 事件驱动的 hook 系统，支持 register/trigger 模式，提供 tool:before/tool:after、agent:start/agent:end、llm:before/llm:after 等关键 hook 点，对调试和安全审计至关重要
3. **可观测性（Observability）** — 基于 OpenTelemetry 的分布式追踪系统，通过诊断事件系统（emit/on 解耦模式）桥接业务代码与 OTEL 导出，P2A 阶段聚焦 Traces 实现

选型决策依据：参考 deer-flow 的 FastAPI Router 模块化架构（单进程模式）、PicoClaw 的热重载和优雅关闭、OpenClaw 的事件驱动 hook 设计和诊断事件系统。详见 `docs/smartclaw-p2a-reference-comparison.md`。

现有代码基础：SmartClaw 已有 structlog 日志系统（`smartclaw/observability/logging.py`）、tracing.py 占位文件、Agent Graph（`smartclaw/agent/graph.py`）、ToolRegistry（`smartclaw/tools/registry.py`）、Pydantic Settings（`smartclaw/config/settings.py`）、CLI（`smartclaw/cli.py`）。

技术栈：Python 3.12+、FastAPI、uvicorn、OpenTelemetry SDK、asyncio、structlog、Pydantic Settings、pytest + hypothesis。

## Glossary

- **API_Gateway**: HTTP 服务层模块，基于 FastAPI 实现，提供 REST API 端点，让 SmartClaw 能作为 HTTP 服务被外部系统调用
- **Gateway_Router**: FastAPI Router 模块，每个功能域（chat、sessions、tools、health）对应一个独立的 Router 文件
- **SSE_Stream**: Server-Sent Events 流式响应，用于实时推送 Agent 执行过程中的中间结果（工具调用、推理步骤）给客户端
- **Lifespan_Manager**: FastAPI 应用生命周期管理器，负责启动时初始化资源和关闭时清理资源
- **Hot_Reload**: 热重载机制，监控配置文件变化并在运行时重新加载配置，无需重启服务
- **Graceful_Shutdown**: 优雅关闭机制，收到终止信号后等待进行中的请求完成再关闭服务
- **Hook_Registry**: Hook 注册表，全局单例，管理所有已注册的 hook handler 函数
- **Hook_Event**: Hook 事件对象，包含事件类型（type）、动作（action）、时间戳和上下文数据
- **Hook_Handler**: Hook 处理函数，异步可调用对象，接收 Hook_Event 并执行自定义逻辑
- **Hook_Point**: Hook 挂载点，定义在 Agent 执行流程中可以插入自定义逻辑的位置（如 tool:before、tool:after）
- **Diagnostic_Event**: 诊断事件，业务代码通过 emit 发出的结构化事件，用于解耦业务逻辑和可观测性实现
- **Diagnostic_Bus**: 诊断事件总线，基于 asyncio 的 emit/on 发布订阅系统，连接业务代码和 OTEL 导出器
- **OTEL_Tracer**: OpenTelemetry Tracer 实例，用于创建和管理分布式追踪的 Span
- **OTEL_Span**: OpenTelemetry Span，表示一个操作的执行时间段，包含名称、属性、状态和父子关系
- **Trace_Context**: 追踪上下文，包含 trace_id 和 span_id，用于关联分布式调用链中的各个 Span
- **AgentState**: P0 已实现的 LangGraph 状态 TypedDict（`smartclaw/agent/state.py`）
- **ToolRegistry**: P0 已实现的工具注册中心（`smartclaw/tools/registry.py`）
- **SmartClawSettings**: P0 已实现的 Pydantic Settings 根配置（`smartclaw/config/settings.py`）
- **FallbackChain**: P0 已实现的 LLM Fallback 调用链（`smartclaw/providers/fallback.py`）

## Requirements

### Requirement 1: API Gateway — FastAPI 应用核心

**User Story:** As a developer, I want SmartClaw to run as an HTTP service with a FastAPI application, so that external systems can interact with the Agent through REST API endpoints instead of only through CLI.

#### Acceptance Criteria

1. THE API_Gateway SHALL provide a FastAPI application instance configured with title "SmartClaw API"、version string、and CORS middleware allowing configurable origins
2. THE API_Gateway SHALL use a Lifespan_Manager (`@asynccontextmanager`) to initialize shared resources (SmartClawSettings, ToolRegistry, Agent Graph, Memory_Store) on startup and release resources on shutdown
3. THE API_Gateway SHALL run as a single process where the Agent runtime and HTTP API coexist, avoiding the complexity of multi-process deployment
4. THE API_Gateway SHALL mount all Gateway_Router modules via `app.include_router` with URL prefix grouping (e.g., `/api/chat`, `/api/sessions`, `/api/tools`, `/api/health`)
5. THE API_Gateway SHALL use Pydantic models for all request body validation and response serialization

### Requirement 2: API Gateway — Chat 路由

**User Story:** As an API consumer, I want to send chat messages to SmartClaw via HTTP and receive responses, so that I can integrate SmartClaw into web applications and automation pipelines.

#### Acceptance Criteria

1. THE Chat_Router SHALL provide a `POST /api/chat` endpoint that accepts a JSON body with required field `message` (string) and optional fields `session_key` (string) and `max_iterations` (integer)
2. WHEN `session_key` is not provided in the request, THE Chat_Router SHALL generate a unique session key using UUID
3. THE Chat_Router SHALL invoke the Agent Graph via the existing `invoke` function from `smartclaw/agent/graph.py`, passing the message, session_key, and configured tools
4. THE Chat_Router SHALL return a JSON response containing fields: `session_key` (string), `response` (string, the Agent's final answer), `iterations` (integer), and `error` (string or null)
5. IF the Agent Graph invocation raises an exception, THEN THE Chat_Router SHALL return an HTTP 500 response with a JSON body containing the error description

### Requirement 3: API Gateway — SSE 流式响应

**User Story:** As an API consumer, I want to receive real-time streaming updates during Agent execution, so that I can display intermediate results (tool calls, reasoning steps) to users without waiting for the complete response.

#### Acceptance Criteria

1. THE Chat_Router SHALL provide a `POST /api/chat/stream` endpoint that accepts the same request body as `POST /api/chat` and returns a Server-Sent Events stream
2. THE SSE_Stream SHALL emit events with type `tool_call` containing the tool name and arguments when the Agent invokes a tool
3. THE SSE_Stream SHALL emit events with type `tool_result` containing the tool execution result when a tool call completes
4. THE SSE_Stream SHALL emit events with type `thinking` containing intermediate reasoning text when the LLM produces partial output
5. THE SSE_Stream SHALL emit a final event with type `done` containing the complete response, session_key, and iteration count
6. IF an error occurs during streaming, THEN THE SSE_Stream SHALL emit an event with type `error` containing the error description and close the stream
7. THE SSE_Stream SHALL use `text/event-stream` content type and follow the SSE protocol format (`data:` prefix, double newline delimiter)

### Requirement 4: API Gateway — Sessions 路由

**User Story:** As an API consumer, I want to manage chat sessions through REST endpoints, so that I can list, retrieve, and clean up conversation sessions.

#### Acceptance Criteria

1. THE Sessions_Router SHALL provide a `GET /api/sessions/{session_key}/history` endpoint that returns the conversation history for the specified session as a JSON array of message objects
2. THE Sessions_Router SHALL provide a `GET /api/sessions/{session_key}/summary` endpoint that returns the conversation summary for the specified session
3. THE Sessions_Router SHALL provide a `DELETE /api/sessions/{session_key}` endpoint that clears the session history and summary from Memory_Store
4. WHEN a session endpoint is called with a session_key that does not exist in Memory_Store, THE Sessions_Router SHALL return an empty history list or empty summary string (not an error)

### Requirement 5: API Gateway — Tools 和 Health 路由

**User Story:** As an API consumer and system operator, I want to query available tools and check service health, so that I can discover Agent capabilities and monitor service status.

#### Acceptance Criteria

1. THE Tools_Router SHALL provide a `GET /api/tools` endpoint that returns a JSON array of all registered tools with fields: `name` (string) and `description` (string)
2. THE Health_Router SHALL provide a `GET /health` endpoint that returns HTTP 200 with a JSON body containing `status` ("ok"), `version` (string), and `tools_count` (integer)
3. THE Health_Router SHALL provide a `GET /ready` endpoint that returns HTTP 200 when the Agent Graph and ToolRegistry are initialized, and HTTP 503 when the service is still starting up

### Requirement 6: API Gateway — 优雅关闭

**User Story:** As a system operator, I want the API Gateway to shut down gracefully when receiving termination signals, so that in-flight requests complete before the service stops.

#### Acceptance Criteria

1. WHEN the API_Gateway receives a SIGTERM or SIGINT signal, THE Graceful_Shutdown mechanism SHALL stop accepting new requests and wait for in-flight requests to complete
2. THE Graceful_Shutdown mechanism SHALL enforce a configurable shutdown timeout (default 30 seconds), after which remaining requests are forcefully terminated
3. WHEN the shutdown timeout is reached, THE API_Gateway SHALL log a warning via structlog indicating the number of requests that were forcefully terminated
4. THE Lifespan_Manager SHALL close Memory_Store connections, release ToolRegistry resources, and perform cleanup in the shutdown phase

### Requirement 7: API Gateway — 热重载

**User Story:** As a system operator, I want the API Gateway to detect configuration file changes and reload settings at runtime, so that I can update Agent behavior without restarting the service.

#### Acceptance Criteria

1. THE Hot_Reload mechanism SHALL monitor the SmartClaw YAML configuration file for changes using file modification time polling at a configurable interval (default 5 seconds)
2. WHEN a configuration file change is detected, THE Hot_Reload mechanism SHALL reload SmartClawSettings and update the shared application state (model config, tool settings, logging level)
3. IF the new configuration file contains invalid YAML or fails Pydantic validation, THEN THE Hot_Reload mechanism SHALL log the validation error and retain the current configuration without applying changes
4. THE Hot_Reload mechanism SHALL emit a `config:reloaded` diagnostic event when configuration is successfully reloaded

### Requirement 8: API Gateway — 配置集成

**User Story:** As a developer, I want API Gateway settings to be configurable via SmartClawSettings, so that I can customize the HTTP service behavior through YAML config or environment variables.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include a `gateway` field of type GatewaySettings with sub-fields: `enabled` (bool, default False), `host` (string, default "0.0.0.0"), `port` (integer, default 8000), `cors_origins` (list of strings, default ["*"]), `shutdown_timeout` (integer, default 30 seconds), and `reload_interval` (integer, default 5 seconds)
2. THE GatewaySettings SHALL support environment variable overrides with prefix `SMARTCLAW_GATEWAY__` (e.g., `SMARTCLAW_GATEWAY__PORT`, `SMARTCLAW_GATEWAY__HOST`)
3. WHEN `gateway.enabled` is False, THE SmartClaw system SHALL operate in CLI-only mode, identical to current behavior

### Requirement 9: Lifecycle Hooks — Hook 注册与触发核心

**User Story:** As a developer, I want an event-driven hook system with register/trigger pattern, so that I can insert custom logic at key points in the Agent execution lifecycle for debugging, auditing, and extensibility.

#### Acceptance Criteria

1. THE Hook_Registry SHALL provide a `register` function that accepts a Hook_Point string (e.g., "tool:before") and a Hook_Handler async callable, and stores the handler in the global registry
2. THE Hook_Registry SHALL provide an `unregister` function that accepts a Hook_Point string and a Hook_Handler reference, and removes the specific handler from the registry
3. THE Hook_Registry SHALL provide a `trigger` async function that accepts a Hook_Point string and a Hook_Event object, and invokes all registered handlers for that Hook_Point in registration order
4. WHEN `trigger` is called for a Hook_Point with no registered handlers, THE Hook_Registry SHALL return immediately without error
5. IF a Hook_Handler raises an exception during execution, THEN THE Hook_Registry SHALL log the error via structlog and continue executing remaining handlers for the same Hook_Point (error isolation)
6. THE Hook_Registry SHALL provide a `clear` function that removes all registered handlers (used for testing)
7. THE Hook_Registry SHALL be implemented as a module-level singleton to ensure consistent state across the application

### Requirement 10: Lifecycle Hooks — Hook 事件类型

**User Story:** As a developer, I want well-defined hook event types covering tool calls, Agent lifecycle, and LLM calls, so that I can observe and intercept key operations in the Agent execution flow.

#### Acceptance Criteria

1. THE Hook system SHALL support the following Hook_Point types: `tool:before`, `tool:after`, `agent:start`, `agent:end`, `llm:before`, `llm:after`, `session:start`, `session:end`
2. THE Hook_Event for `tool:before` SHALL contain fields: `tool_name` (string), `tool_args` (dict), `tool_call_id` (string), and `timestamp` (ISO 8601 string)
3. THE Hook_Event for `tool:after` SHALL contain fields: `tool_name` (string), `tool_args` (dict), `tool_call_id` (string), `result` (string), `duration_ms` (float), `error` (string or None), and `timestamp` (ISO 8601 string)
4. THE Hook_Event for `agent:start` SHALL contain fields: `session_key` (string or None), `user_message` (string), `tools_count` (integer), and `timestamp` (ISO 8601 string)
5. THE Hook_Event for `agent:end` SHALL contain fields: `session_key` (string or None), `final_answer` (string or None), `iterations` (integer), `error` (string or None), and `timestamp` (ISO 8601 string)
6. THE Hook_Event for `llm:before` SHALL contain fields: `model` (string), `message_count` (integer), `has_tools` (boolean), and `timestamp` (ISO 8601 string)
7. THE Hook_Event for `llm:after` SHALL contain fields: `model` (string), `has_tool_calls` (boolean), `duration_ms` (float), `error` (string or None), and `timestamp` (ISO 8601 string)
8. THE Hook_Event for `session:start` and `session:end` SHALL contain fields: `session_key` (string) and `timestamp` (ISO 8601 string)

### Requirement 11: Lifecycle Hooks — Agent Graph 集成

**User Story:** As a developer, I want lifecycle hooks to be automatically triggered at the correct points in the Agent execution flow, so that hook handlers receive events without requiring manual instrumentation in business code.

#### Acceptance Criteria

1. WHEN the `invoke` function in `smartclaw/agent/graph.py` starts processing a user message, THE Agent Graph SHALL trigger the `agent:start` hook with the user message and session context
2. WHEN the `invoke` function completes (success or error), THE Agent Graph SHALL trigger the `agent:end` hook with the final answer, iteration count, and error information
3. WHEN the `action_node` in `smartclaw/agent/nodes.py` is about to execute a tool call, THE action_node SHALL trigger the `tool:before` hook with the tool name, arguments, and tool_call_id
4. WHEN the `action_node` completes a tool call (success or error), THE action_node SHALL trigger the `tool:after` hook with the tool name, result, duration, and error information
5. WHEN the `reasoning_node` is about to call the LLM, THE reasoning_node SHALL trigger the `llm:before` hook with the model name, message count, and tools binding status
6. WHEN the `reasoning_node` completes the LLM call, THE reasoning_node SHALL trigger the `llm:after` hook with the model name, tool_calls presence, duration, and error information
7. THE hook trigger calls SHALL be non-blocking — hook execution failures SHALL NOT affect the Agent's normal execution flow

### Requirement 12: Lifecycle Hooks — Hook 事件序列化往返

**User Story:** As a developer, I want Hook events to be serializable to JSON and deserializable back without data loss, so that hook events can be persisted, transmitted, and replayed for debugging and auditing.

#### Acceptance Criteria

1. THE Hook_Event SHALL provide a `to_dict` method that returns a JSON-serializable dictionary representation of the event
2. THE Hook_Event SHALL provide a `from_dict` class method that accepts a dictionary and returns a Hook_Event instance
3. FOR ALL valid Hook_Event instances, converting to dict and back SHALL produce an equivalent Hook_Event (round-trip property)

### Requirement 13: Observability — 诊断事件总线

**User Story:** As a developer, I want a diagnostic event bus that decouples business code from observability implementation, so that business code only needs to emit events and the OTEL export is handled separately by subscribers.

#### Acceptance Criteria

1. THE Diagnostic_Bus SHALL provide an `emit` async function that accepts an event type string (e.g., "model.usage", "tool.executed") and a payload dictionary, and dispatches the event to all registered subscribers
2. THE Diagnostic_Bus SHALL provide an `on` function that accepts an event type string and a subscriber async callable, and registers the subscriber to receive events of that type
3. THE Diagnostic_Bus SHALL provide an `off` function that accepts an event type string and a subscriber reference, and removes the specific subscriber
4. WHEN `emit` is called for an event type with no subscribers, THE Diagnostic_Bus SHALL return immediately without error
5. IF a subscriber raises an exception during event processing, THEN THE Diagnostic_Bus SHALL log the error via structlog and continue dispatching to remaining subscribers (error isolation)
6. THE Diagnostic_Bus SHALL provide a `clear` function that removes all registered subscribers (used for testing)
7. THE Diagnostic_Bus SHALL be implemented as a module-level singleton to ensure consistent state across the application

### Requirement 14: Observability — 诊断事件类型

**User Story:** As a developer, I want well-defined diagnostic event types covering tool execution, LLM usage, and Agent runs, so that OTEL subscribers can create meaningful traces and spans from structured event data.

#### Acceptance Criteria

1. THE Diagnostic_Bus SHALL support the following event types: `tool.executed`, `llm.called`, `agent.run`, `session.started`, `session.ended`, `config.reloaded`
2. THE `tool.executed` event payload SHALL contain fields: `tool_name` (string), `duration_ms` (float), `success` (boolean), `error` (string or None)
3. THE `llm.called` event payload SHALL contain fields: `model` (string), `duration_ms` (float), `has_tool_calls` (boolean), `message_count` (integer), `error` (string or None)
4. THE `agent.run` event payload SHALL contain fields: `session_key` (string or None), `iterations` (integer), `duration_ms` (float), `success` (boolean), `error` (string or None)
5. THE `session.started` and `session.ended` event payloads SHALL contain field: `session_key` (string)
6. THE `config.reloaded` event payload SHALL contain fields: `changed_fields` (list of strings), `success` (boolean)

### Requirement 15: Observability — OpenTelemetry Traces

**User Story:** As a system operator, I want distributed tracing for Agent execution using OpenTelemetry, so that I can visualize the complete call chain (Agent → LLM → Tool calls) in tracing backends like Jaeger or Grafana Tempo.

#### Acceptance Criteria

1. THE OTEL_Tracer module SHALL initialize an OpenTelemetry TracerProvider with a configurable service name (default "smartclaw") and OTLP exporter endpoint
2. THE OTEL_Tracer module SHALL create a root Span named "agent.invoke" for each Agent Graph invocation, with attributes: `session_key`, `user_message` (truncated to 256 characters), and `max_iterations`
3. THE OTEL_Tracer module SHALL create child Spans named "llm.call" for each LLM invocation within the Agent loop, with attributes: `model`, `message_count`, and `has_tools`
4. THE OTEL_Tracer module SHALL create child Spans named "tool.execute.{tool_name}" for each tool call, with attributes: `tool_name`, `tool_call_id`, and `success` (boolean)
5. WHEN a Span represents a failed operation, THE OTEL_Tracer module SHALL set the Span status to ERROR and record the error message as a Span event
6. THE OTEL_Tracer module SHALL use `BatchSpanProcessor` for efficient Span export, with configurable flush interval
7. THE OTEL_Tracer module SHALL support both OTLP HTTP and OTLP gRPC export protocols, configurable via settings
8. WHEN OpenTelemetry is disabled in configuration, THE OTEL_Tracer module SHALL use a NoOp TracerProvider that produces no-op Spans, ensuring zero overhead when tracing is off

### Requirement 16: Observability — OTEL 与诊断事件集成

**User Story:** As a developer, I want the OTEL tracing to be driven by diagnostic events rather than direct instrumentation, so that the tracing implementation is decoupled from business code and can be replaced or extended independently.

#### Acceptance Criteria

1. THE OTEL integration module SHALL subscribe to `tool.executed` diagnostic events and create corresponding tool Spans with duration and status attributes
2. THE OTEL integration module SHALL subscribe to `llm.called` diagnostic events and create corresponding LLM Spans with model and duration attributes
3. THE OTEL integration module SHALL subscribe to `agent.run` diagnostic events and finalize the root Agent Span with iteration count and final status
4. THE OTEL integration module SHALL be initialized during application startup (in Lifespan_Manager or CLI startup) and register all diagnostic event subscribers
5. WHEN the OTEL integration module is not initialized (tracing disabled), THE Diagnostic_Bus SHALL still function normally — diagnostic events are emitted but no OTEL Spans are created

### Requirement 17: Observability — 敏感数据脱敏

**User Story:** As a security-conscious operator, I want sensitive data to be redacted before being exported to tracing backends, so that API keys, passwords, and personal information are not leaked through observability data.

#### Acceptance Criteria

1. THE OTEL_Tracer module SHALL apply a redaction function to all Span attributes before export, replacing values matching sensitive patterns (API keys, passwords, tokens, email addresses) with "[REDACTED]"
2. THE redaction function SHALL detect patterns including: strings starting with "sk-", "key-", or "token-"; strings containing "@" (email-like); and environment variable values matching common secret names (API_KEY, SECRET, PASSWORD, TOKEN)
3. THE redaction function SHALL truncate long string attributes to a configurable maximum length (default 1024 characters) to prevent excessive data export
4. THE `user_message` attribute on the root Agent Span SHALL be truncated to 256 characters to limit personal data exposure

### Requirement 18: Observability — 配置集成

**User Story:** As a developer, I want observability settings to be configurable via SmartClawSettings, so that I can enable/disable tracing and configure OTEL export endpoints through YAML config or environment variables.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include an `observability` field of type ObservabilitySettings with sub-fields: `tracing_enabled` (bool, default False), `otlp_endpoint` (string, default "http://localhost:4318"), `otlp_protocol` (string, default "http/protobuf", options: "http/protobuf" or "grpc"), `service_name` (string, default "smartclaw"), `sample_rate` (float, default 1.0, range 0.0-1.0), and `redact_sensitive` (bool, default True)
2. THE ObservabilitySettings SHALL support environment variable overrides with prefix `SMARTCLAW_OBSERVABILITY__` (e.g., `SMARTCLAW_OBSERVABILITY__TRACING_ENABLED`, `SMARTCLAW_OBSERVABILITY__OTLP_ENDPOINT`)
3. THE ObservabilitySettings SHALL also respect standard OTEL environment variables (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`) as fallback when SmartClaw-specific variables are not set
4. WHEN `observability.tracing_enabled` is False, THE OTEL_Tracer module SHALL skip TracerProvider initialization and use NoOp tracing, ensuring zero performance overhead

### Requirement 19: Agent Graph 诊断事件埋点

**User Story:** As a developer, I want the existing Agent Graph nodes to emit diagnostic events at key execution points, so that the observability system can create traces without modifying the core Agent logic.

#### Acceptance Criteria

1. WHEN the `invoke` function starts processing, THE Agent Graph SHALL emit an `agent.run` diagnostic event with `phase` set to "start"
2. WHEN the `invoke` function completes, THE Agent Graph SHALL emit an `agent.run` diagnostic event with `phase` set to "end", including iteration count, duration, and error information
3. WHEN the `action_node` executes a tool call, THE action_node SHALL emit a `tool.executed` diagnostic event with tool name, duration, success status, and error information
4. WHEN the `reasoning_node` completes an LLM call, THE reasoning_node SHALL emit an `llm.called` diagnostic event with model name, duration, tool_calls presence, and error information
5. THE diagnostic event emission SHALL be non-blocking — emission failures SHALL NOT affect the Agent's normal execution flow

### Requirement 20: P2A 模块与现有系统的向后兼容

**User Story:** As a developer, I want all P2A modules to be backward compatible with the existing P0/P1 system, so that existing CLI functionality and all P1 features continue to work without modification when P2A modules are disabled.

#### Acceptance Criteria

1. WHEN all P2A module settings (`gateway.enabled` is False, `observability.tracing_enabled` is False) are set to disabled, THE SmartClaw system SHALL behave identically to the P1 system with no functional differences
2. THE P2A modules SHALL not modify any existing P0/P1 module interfaces (AgentState, build_graph, invoke, ToolRegistry, SmartClawSettings existing fields, MemoryStore, SkillsLoader, SubAgent)
3. THE P2A modules SHALL extend SmartClawSettings with new optional fields (gateway, observability) using default values that disable the new features, maintaining compatibility with existing YAML configurations
4. THE Hook system SHALL be available even when the API Gateway is disabled, allowing CLI mode to benefit from hook-based debugging and auditing
5. THE diagnostic event system SHALL be available even when OTEL tracing is disabled, allowing other subscribers (logging, metrics) to consume events independently
