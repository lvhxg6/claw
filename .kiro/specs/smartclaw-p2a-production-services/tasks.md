# Implementation Plan: SmartClaw P2A 生产级服务

## Overview

实现 SmartClaw P2A 阶段 3 个生产级服务模块：生命周期 Hook 系统、诊断事件总线 + OTEL Traces、API 网关。

所有新代码位于 `smartclaw/smartclaw/hooks/`、`smartclaw/smartclaw/observability/`（新增/修改）、`smartclaw/smartclaw/gateway/`、`smartclaw/smartclaw/config/settings.py`（修改），测试位于 `smartclaw/tests/hooks/`、`smartclaw/tests/observability/`、`smartclaw/tests/gateway/`、`smartclaw/tests/config/`（新增）。需新增 `fastapi`、`uvicorn`、`httpx`、`opentelemetry-sdk`、`opentelemetry-exporter-otlp` 依赖到 `pyproject.toml`。

实现按依赖顺序推进：P2A 配置模型 → Hook 系统（基础设施）→ 诊断事件总线 → OTEL Traces → 敏感数据脱敏 → API 网关 → Agent Graph 集成 → 向后兼容验证。

## Tasks

- [x] 1. P2A 配置模型与项目脚手架
  - [x] 1.1 添加 P2A 依赖并创建包结构
    - 在 `pyproject.toml` 中添加 `fastapi>=0.115.0`、`uvicorn>=0.30.0`、`httpx>=0.27.0`、`opentelemetry-sdk>=1.25.0`、`opentelemetry-exporter-otlp>=1.25.0` 依赖
    - 创建 `smartclaw/smartclaw/hooks/__init__.py`、`smartclaw/smartclaw/gateway/__init__.py`、`smartclaw/smartclaw/gateway/routers/__init__.py`
    - 创建 `smartclaw/tests/hooks/__init__.py`、`smartclaw/tests/gateway/__init__.py`、`smartclaw/tests/observability/__init__.py`
    - _Requirements: 1.1, 8.1, 18.1_

  - [x] 1.2 实现 `GatewaySettings` 和 `ObservabilitySettings` 配置模型 (`smartclaw/smartclaw/config/settings.py`)
    - 实现 `GatewaySettings(BaseSettings)`: enabled (default False), host, port, cors_origins, shutdown_timeout, reload_interval
    - 实现 `ObservabilitySettings(BaseSettings)`: tracing_enabled (default False), otlp_endpoint, otlp_protocol, service_name, sample_rate, redact_sensitive
    - 在 `SmartClawSettings` 中添加 `gateway: GatewaySettings` 和 `observability: ObservabilitySettings` 字段
    - 所有新字段使用 `Field(default_factory=...)` 确保默认禁用
    - _Requirements: 8.1, 8.2, 8.3, 18.1, 18.2, 18.4_

  - [x] 1.3 编写属性测试：P2A 设置环境变量覆盖 (`tests/config/test_p2a_settings_props.py`)
    - **Property 8: P2A 设置环境变量覆盖**
    - 对任意以 `SMARTCLAW_GATEWAY__` 或 `SMARTCLAW_OBSERVABILITY__` 为前缀的环境变量，对应的 GatewaySettings 或 ObservabilitySettings 字段值应被环境变量值覆盖
    - **Validates: Requirements 8.2, 18.2**

  - [x] 1.4 编写单元测试 (`tests/config/test_p2a_settings.py`)
    - 测试 GatewaySettings 所有字段默认值正确 (Req 8.1)
    - 测试 ObservabilitySettings 所有字段默认值正确 (Req 18.1)
    - 测试 gateway.enabled=False 时系统以 CLI-only 模式运行 (Req 8.3)
    - 测试 observability.tracing_enabled=False 时使用 NoOp TracerProvider (Req 18.4)
    - 测试环境变量覆盖 SMARTCLAW_GATEWAY__PORT 等 (Req 8.2, 18.2)
    - 测试 SmartClawSettings 现有 P0/P1 字段未被修改 (Req 20.2, 20.3)
    - _Requirements: 8.1, 8.2, 8.3, 18.1, 18.2, 18.4, 20.2, 20.3_

- [x] 2. Checkpoint — 确认 P2A 配置模型测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. 生命周期 Hook 系统 — 事件类型与注册表
  - [x] 3.1 实现 Hook 事件类型 (`smartclaw/smartclaw/hooks/events.py`)
    - 实现 `HookEvent` 基类 (`@dataclass(frozen=True)`)：hook_point, timestamp (ISO 8601)
    - 实现 `to_dict()` 方法返回 JSON 可序列化字典
    - 实现 `from_dict(data)` 类方法根据 hook_point 反序列化为对应子类
    - 实现 8 个子类：`ToolBeforeEvent`, `ToolAfterEvent`, `AgentStartEvent`, `AgentEndEvent`, `LLMBeforeEvent`, `LLMAfterEvent`, `SessionStartEvent`, `SessionEndEvent`
    - 每个子类包含设计文档中定义的所有字段
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [x] 3.2 实现 Hook 注册表 (`smartclaw/smartclaw/hooks/registry.py`)
    - 定义 `VALID_HOOK_POINTS` frozenset：8 个合法 hook 点
    - 实现 `register(hook_point, handler)` 注册 handler，无效 hook_point 抛出 ValueError
    - 实现 `unregister(hook_point, handler)` 注销指定 handler
    - 实现 `trigger(hook_point, event)` 异步触发所有 handler，按注册顺序执行，单个异常不影响其他（错误隔离）
    - 实现 `clear()` 清除所有 handler（测试用）
    - 模块级单例实现
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 3.3 编写属性测试：HookEvent 子类包含必需字段 (`tests/hooks/test_events_props.py`)
    - **Property 12: HookEvent 子类包含必需字段**
    - 对任意 HookEvent 子类实例，`to_dict()` 返回的字典包含该事件类型规定的所有必需字段键，且 `timestamp` 为有效 ISO 8601 格式
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8**

  - [x] 3.4 编写属性测试：HookEvent 序列化往返 (`tests/hooks/test_events_props.py`)
    - **Property 13: HookEvent 序列化往返**
    - 对任意有效 HookEvent 子类实例，`HookEvent.from_dict(event.to_dict())` 产生与原始实例等价的对象
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [x] 3.5 编写属性测试：Hook register/unregister 往返 (`tests/hooks/test_registry_props.py`)
    - **Property 9: Hook register/unregister 往返**
    - 对任意合法 hook_point 和 handler，register 后 trigger 可调用该 handler；unregister 后 trigger 不再调用
    - **Validates: Requirements 9.1, 9.2**

  - [x] 3.6 编写属性测试：Hook trigger 按注册顺序执行 (`tests/hooks/test_registry_props.py`)
    - **Property 10: Hook trigger 按注册顺序执行**
    - 对任意同一 hook_point 上注册的 N 个 handler（N ≥ 2），trigger 按注册顺序依次调用
    - **Validates: Requirements 9.3**

  - [x] 3.7 编写属性测试：Hook 错误隔离 (`tests/hooks/test_registry_props.py`)
    - **Property 11: Hook 错误隔离**
    - 对任意 handler 集合中部分抛出异常，所有未抛异常的 handler 仍被正常调用，trigger 本身不抛异常
    - **Validates: Requirements 9.5, 11.7**

  - [x] 3.8 编写单元测试 (`tests/hooks/test_events.py`, `tests/hooks/test_registry.py`)
    - 测试各事件类型构造和字段值 (Req 10.2–10.8)
    - 测试 to_dict/from_dict 具体示例 (Req 12.1, 12.2)
    - 测试无效 hook_point 注册抛出 ValueError (Req 9.1)
    - 测试 trigger 空 hook_point 立即返回 (Req 9.4)
    - 测试 clear 清除所有 handler (Req 9.6)
    - _Requirements: 9.1, 9.4, 9.6, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 12.1, 12.2_

- [x] 4. Checkpoint — 确认 Hook 系统测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. 诊断事件总线
  - [x] 5.1 实现诊断事件总线 (`smartclaw/smartclaw/observability/diagnostic_bus.py`)
    - 实现 `emit(event_type, payload)` 异步分发事件到所有订阅者，单个异常不影响其他（错误隔离）
    - 实现 `on(event_type, subscriber)` 注册订阅者
    - 实现 `off(event_type, subscriber)` 注销订阅者
    - 实现 `clear()` 清除所有订阅者（测试用）
    - 无订阅者时 emit 立即返回
    - 模块级单例实现
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 5.2 编写属性测试：诊断事件总线分发到所有订阅者 (`tests/observability/test_diagnostic_bus_props.py`)
    - **Property 14: 诊断事件总线分发到所有订阅者**
    - 对任意事件类型和 N 个订阅者，emit 后所有 N 个订阅者都收到该事件
    - **Validates: Requirements 13.1**

  - [x] 5.3 编写属性测试：诊断事件总线 on/off 往返 (`tests/observability/test_diagnostic_bus_props.py`)
    - **Property 15: 诊断事件总线 on/off 往返**
    - 对任意事件类型和订阅者，on 注册后能收到 emit 事件；off 注销后不再收到
    - **Validates: Requirements 13.2, 13.3**

  - [x] 5.4 编写属性测试：诊断事件总线错误隔离 (`tests/observability/test_diagnostic_bus_props.py`)
    - **Property 16: 诊断事件总线错误隔离**
    - 对任意订阅者集合中部分抛出异常，所有未抛异常的订阅者仍收到事件，emit 不抛异常
    - **Validates: Requirements 13.5**

  - [x] 5.5 编写属性测试：诊断事件总线独立于 OTEL (`tests/observability/test_diagnostic_bus_props.py`)
    - **Property 19: 诊断事件总线独立于 OTEL**
    - 即使没有 OTEL 订阅者（tracing_enabled=False），emit 正常完成不抛异常，其他订阅者正常收到事件
    - **Validates: Requirements 16.5, 19.5**

  - [x] 5.6 编写单元测试 (`tests/observability/test_diagnostic_bus.py`)
    - 测试 emit 无订阅者时立即返回 (Req 13.4)
    - 测试 clear 清除所有订阅者 (Req 13.6)
    - 测试异常订阅者 structlog 记录错误 (Req 13.5)
    - 测试支持的事件类型：tool.executed, llm.called, agent.run, session.started, session.ended, config.reloaded (Req 14.1)
    - _Requirements: 13.4, 13.5, 13.6, 14.1_

- [x] 6. Checkpoint — 确认诊断事件总线测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. OTEL Traces 与敏感数据脱敏
  - [x] 7.1 实现敏感数据脱敏模块 (`smartclaw/smartclaw/observability/redaction.py`)
    - 实现 `_SENSITIVE_PATTERNS` 正则列表：sk- 前缀、key- 前缀、token- 前缀、email 格式
    - 实现 `_SECRET_ENV_NAMES` frozenset：API_KEY, SECRET, PASSWORD, TOKEN, PRIVATE_KEY
    - 实现 `redact_value(value)` 检测并脱敏单个字符串，匹配时返回 "[REDACTED]"
    - 实现 `redact_attributes(attrs, max_length=1024)` 对所有字符串属性执行脱敏 + 截断
    - 实现 `truncate_string(value, max_length=1024)` 截断超长字符串
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [x] 7.2 编写属性测试：敏感数据脱敏 (`tests/observability/test_redaction_props.py`)
    - **Property 17: 敏感数据脱敏**
    - 对任意匹配敏感模式的字符串，`redact_value()` 返回 "[REDACTED]"；对任意不匹配的普通字符串，返回原始字符串
    - **Validates: Requirements 17.1, 17.2**

  - [x] 7.3 编写属性测试：字符串截断 (`tests/observability/test_redaction_props.py`)
    - **Property 18: 字符串截断**
    - 对任意长度超过 max_length 的字符串，`truncate_string()` 返回长度 ≤ max_length；对任意长度 ≤ max_length 的字符串，返回原始字符串不变
    - **Validates: Requirements 17.3**

  - [x] 7.4 实现 OTEL Traces 服务 (`smartclaw/smartclaw/observability/tracing.py`)
    - 实现 `OTELTracingService` 类：初始化 TracerProvider + BatchSpanProcessor + OTLP exporter
    - 实现 `initialize()` 方法：tracing_enabled=False 时使用 NoOp TracerProvider
    - 实现 `subscribe_to_diagnostic_bus()` 订阅 tool.executed / llm.called / agent.run 事件
    - 实现 `_on_agent_run()` 处理 agent.run 事件：phase=start 创建 root span，phase=end 结束 span
    - 实现 `_on_llm_called()` 创建 child span "llm.call"
    - 实现 `_on_tool_executed()` 创建 child span "tool.execute.{name}"
    - 所有 Span 属性通过 `redact_attributes()` 脱敏后再设置
    - 失败操作设置 Span status 为 ERROR 并记录错误事件
    - 实现 `shutdown()` flush 并关闭 TracerProvider
    - 实现 `setup_tracing(settings)` 便捷函数
    - 支持 OTLP HTTP 和 gRPC 两种协议
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 16.1, 16.2, 16.3, 16.4, 16.5, 17.1, 18.3, 18.4_

  - [x] 7.5 编写单元测试 (`tests/observability/test_redaction.py`)
    - 测试各敏感模式匹配：sk- 前缀、key- 前缀、token- 前缀、email 格式 (Req 17.2)
    - 测试非敏感字符串不被脱敏
    - 测试截断边界：恰好 max_length、超过 1 字符、远超 max_length (Req 17.3)
    - 测试 user_message 截断到 256 字符 (Req 17.4)
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [x] 7.6 编写单元测试 (`tests/observability/test_tracing.py`)
    - 测试 TracerProvider 初始化成功 (Req 15.1)
    - 测试 tracing_enabled=False 时使用 NoOp TracerProvider (Req 15.8)
    - 测试 root span "agent.invoke" 创建和属性 (Req 15.2)
    - 测试 child span "llm.call" 创建和属性 (Req 15.3)
    - 测试 child span "tool.execute.{name}" 创建和属性 (Req 15.4)
    - 测试失败操作 Span status 为 ERROR (Req 15.5)
    - 测试 shutdown flush spans (Req 15.6)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.8_

  - [x] 7.7 编写 OTEL 集成测试 (`tests/observability/test_otel_integration.py`)
    - 测试诊断事件 → OTEL Span 完整链路：emit("agent.run") → root span 创建
    - 测试 emit("llm.called") → child span 创建
    - 测试 emit("tool.executed") → child span 创建
    - 测试 tracing_enabled=False 时 emit 正常但无 Span 创建 (Req 16.5)
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

- [x] 8. Checkpoint — 确认 OTEL Traces 和脱敏测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [-] 9. API 网关 — Pydantic 模型与 FastAPI 应用
  - [x] 9.1 实现 Pydantic 请求/响应模型 (`smartclaw/smartclaw/gateway/models.py`)
    - 实现 `ChatRequest`: message (str, min_length=1), session_key (str | None), max_iterations (int | None)
    - 实现 `ChatResponse`: session_key, response, iterations, error
    - 实现 `SSEEvent`: event (str), data (dict)
    - 实现 `ToolInfo`: name, description
    - 实现 `HealthResponse`: status, version, tools_count
    - 实现 `SessionHistoryResponse`: session_key, messages
    - 实现 `SessionSummaryResponse`: session_key, summary
    - _Requirements: 1.5, 2.1, 2.4_

  - [x] 9.2 编写属性测试：Pydantic 请求校验拒绝无效输入 (`tests/gateway/test_models_props.py`)
    - **Property 1: Pydantic 请求校验拒绝无效输入**
    - 对任意违反 ChatRequest schema 的 JSON body（message 为空、max_iterations 为负数、缺少 message），Pydantic 应抛出 ValidationError
    - **Validates: Requirements 1.5**

  - [x] 9.3 实现 FastAPI 应用核心 (`smartclaw/smartclaw/gateway/app.py`)
    - 实现 `lifespan()` asynccontextmanager：启动时初始化 Settings/ToolRegistry/Graph/MemoryStore，关闭时清理资源
    - 实现 `create_app(settings)` 创建 FastAPI 实例，配置 title/version/CORS/include_router
    - 挂载所有 Router 模块
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 9.4 实现 Chat 路由 (`smartclaw/smartclaw/gateway/routers/chat.py`)
    - 实现 `POST /api/chat` 端点：接受 ChatRequest，调用 Agent Graph invoke，返回 ChatResponse
    - 未提供 session_key 时自动生成 UUID
    - Agent Graph 异常时返回 HTTP 500
    - 实现 `POST /api/chat/stream` SSE 流式端点：推送 tool_call/tool_result/thinking/done/error 事件
    - SSE 使用 text/event-stream content type，遵循 SSE 协议格式
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 9.5 编写属性测试：Chat 响应完整性与自动 session_key (`tests/gateway/test_chat_props.py`)
    - **Property 2: Chat 响应完整性与自动 session_key**
    - 对任意有效 ChatRequest，POST /api/chat 响应包含所有必需字段；未提供 session_key 时响应中为有效 UUID
    - **Validates: Requirements 2.2, 2.4**

  - [x] 9.6 编写属性测试：SSE 协议格式合规 (`tests/gateway/test_sse_props.py`)
    - **Property 3: SSE 协议格式合规**
    - 对任意 POST /api/chat/stream 的 SSE 响应，Content-Type 为 text/event-stream，每个事件遵循 SSE 协议格式
    - **Validates: Requirements 3.7**

  - [x] 9.7 实现 Sessions 路由 (`smartclaw/smartclaw/gateway/routers/sessions.py`)
    - 实现 `GET /api/sessions/{session_key}/history` 返回会话历史
    - 实现 `GET /api/sessions/{session_key}/summary` 返回会话摘要
    - 实现 `DELETE /api/sessions/{session_key}` 清除会话
    - 不存在的 session_key 返回空结果（不返回错误）
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 9.8 编写属性测试：不存在的 session 返回空结果 (`tests/gateway/test_sessions_props.py`)
    - **Property 4: 不存在的 session 返回空结果**
    - 对任意随机 session_key，history 返回空列表，summary 返回空字符串，均不返回错误状态码
    - **Validates: Requirements 4.4**

  - [x] 9.9 实现 Tools 和 Health 路由 (`smartclaw/smartclaw/gateway/routers/tools.py`, `smartclaw/smartclaw/gateway/routers/health.py`)
    - 实现 `GET /api/tools` 返回所有已注册工具列表
    - 实现 `GET /health` 返回 status/version/tools_count
    - 实现 `GET /ready` 返回 200（就绪）或 503（未就绪）
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 9.10 编写属性测试：Tools 端点返回所有已注册工具 (`tests/gateway/test_tools_props.py`)
    - **Property 5: Tools 端点返回所有已注册工具**
    - 对任意 ToolRegistry 中注册的工具集合，GET /api/tools 返回的列表与 ToolRegistry 一一对应
    - **Validates: Requirements 5.1**

  - [x] 9.11 编写单元测试 (`tests/gateway/test_app.py`, `tests/gateway/test_chat.py`, `tests/gateway/test_sessions.py`, `tests/gateway/test_health.py`)
    - 测试 create_app 返回 FastAPI 实例、路由挂载、CORS 配置 (Req 1.1, 1.4)
    - 测试 POST /api/chat 正常响应 (Req 2.1, 2.3, 2.4)
    - 测试 POST /api/chat Agent 异常返回 500 (Req 2.5)
    - 测试 SSE 事件类型：tool_call, tool_result, thinking, done, error (Req 3.2, 3.3, 3.4, 3.5, 3.6)
    - 测试 history/summary/delete 端点 (Req 4.1, 4.2, 4.3)
    - 测试 /health 和 /ready 端点 (Req 5.2, 5.3)
    - _Requirements: 1.1, 1.4, 2.1, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 5.2, 5.3_

- [ ] 10. Checkpoint — 确认 API 网关核心路由测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. API 网关 — 热重载与优雅关闭
  - [ ] 11.1 实现热重载器 (`smartclaw/smartclaw/gateway/hot_reload.py`)
    - 实现 `HotReloader` 类：轮询配置文件 mtime，检测变化后重新加载
    - 实现 `start()` 启动轮询 asyncio.Task
    - 实现 `stop()` 停止轮询
    - 实现 `_poll_loop()` 轮询循环
    - 实现 `_reload()` 重新加载：解析 YAML → Pydantic 校验 → 更新 app.state；校验失败保留旧配置并记录错误；成功时 emit config.reloaded 诊断事件
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 11.2 编写属性测试：有效配置变更触发热重载 (`tests/gateway/test_hot_reload_props.py`)
    - **Property 6: 有效配置变更触发热重载**
    - 对任意有效 YAML 配置文件变更，HotReloader 在下一个轮询周期内检测到变更并成功更新 SmartClawSettings
    - **Validates: Requirements 7.2**

  - [ ] 11.3 编写属性测试：无效配置保留当前设置 (`tests/gateway/test_hot_reload_props.py`)
    - **Property 7: 无效配置保留当前设置**
    - 对任意无效 YAML 或不通过 Pydantic 校验的配置，HotReloader 保留当前配置不变并记录错误日志
    - **Validates: Requirements 7.3**

  - [ ] 11.4 实现优雅关闭机制（集成到 `gateway/app.py` lifespan 和 `serve.py`）
    - 实现 `serve.py` uvicorn 启动入口：加载配置 → 创建 app → 注册 signal handler → 启动 uvicorn
    - SIGTERM/SIGINT 时停止接受新请求，等待进行中请求完成
    - 超时后强制终止并记录 structlog 警告
    - lifespan shutdown 阶段：关闭 MemoryStore、释放 ToolRegistry、flush OTEL spans、停止 HotReloader
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ] 11.5 编写单元测试 (`tests/gateway/test_hot_reload.py`)
    - 测试 mtime 变化检测 (Req 7.1)
    - 测试 reload 成功更新配置 (Req 7.2)
    - 测试 reload 失败保留旧配置 (Req 7.3)
    - 测试 config.reloaded 诊断事件发送 (Req 7.4)
    - 测试 start/stop 生命周期
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 12. Checkpoint — 确认热重载与优雅关闭测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Agent Graph 集成 — Hook 触发与诊断事件埋点
  - [ ] 13.1 修改 `agent/graph.py` 插入 Hook 触发和诊断事件 emit
    - `invoke()` 函数首部插入 `hook.trigger("agent:start", AgentStartEvent(...))` 和 `diagnostic_bus.emit("agent.run", {"phase": "start", ...})`
    - `invoke()` 函数尾部插入 `hook.trigger("agent:end", AgentEndEvent(...))` 和 `diagnostic_bus.emit("agent.run", {"phase": "end", ...})`
    - `_llm_call_with_fallback()` 前后插入 `hook.trigger("llm:before/after", ...)` 和 `diagnostic_bus.emit("llm.called", ...)`
    - 所有 hook trigger 和 diagnostic emit 使用 try/except 包裹，确保不影响正常执行流
    - _Requirements: 11.1, 11.2, 11.5, 11.6, 11.7, 19.1, 19.2, 19.4, 19.5_

  - [ ] 13.2 修改 `agent/nodes.py` 插入 Hook 触发和诊断事件 emit
    - `action_node()` 每个 tool call 前后插入 `hook.trigger("tool:before/after", ...)` 和 `diagnostic_bus.emit("tool.executed", ...)`
    - `reasoning_node()` LLM 调用前后插入 `hook.trigger("llm:before/after", ...)` 和 `diagnostic_bus.emit("llm.called", ...)`
    - 所有 hook trigger 和 diagnostic emit 使用 try/except 包裹
    - _Requirements: 11.3, 11.4, 11.5, 11.6, 11.7, 19.3, 19.4, 19.5_

  - [ ] 13.3 编写 Hook 集成测试 (`tests/hooks/test_integration.py`)
    - 测试 invoke 触发 agent:start 和 agent:end hook (Req 11.1, 11.2)
    - 测试 action_node 触发 tool:before 和 tool:after hook (Req 11.3, 11.4)
    - 测试 reasoning_node 触发 llm:before 和 llm:after hook (Req 11.5, 11.6)
    - 测试 hook 异常不影响 Agent 正常执行 (Req 11.7)
    - 测试诊断事件 emit 与 hook trigger 同步触发 (Req 19.1, 19.3, 19.4)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 19.1, 19.3, 19.4_

- [ ] 14. Checkpoint — 确认 Agent Graph 集成测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. 向后兼容验证与最终集成
  - [ ] 15.1 验证 P2A 模块向后兼容性
    - 确认所有 P2A 模块禁用时（gateway.enabled=False, observability.tracing_enabled=False），系统行为与 P1 完全一致
    - 确认 P2A 模块未修改任何 P0/P1 模块接口（AgentState, build_graph, invoke, ToolRegistry, SmartClawSettings 现有字段, MemoryStore, SkillsLoader, SubAgent）
    - 确认 P2A 模块 import 使用 try/except 包裹，P2A 依赖未安装时静默降级
    - 确认 Hook 系统在 CLI 模式下也可用 (Req 20.4)
    - 确认诊断事件系统在 OTEL 禁用时也可用 (Req 20.5)
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_

  - [ ] 15.2 编写向后兼容集成测试 (`tests/test_backward_compat.py`)
    - 测试所有 P2A 开关关闭时 invoke 行为与 P1 一致 (Req 20.1)
    - 测试 SmartClawSettings 现有 P0/P1 字段未被修改 (Req 20.2)
    - 测试 P2A 新增字段默认禁用，兼容现有 YAML 配置 (Req 20.3)
    - 测试 Hook 系统在 CLI 模式下可用 (Req 20.4)
    - 测试诊断事件系统在 OTEL 禁用时可用 (Req 20.5)
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_

- [ ] 16. Final checkpoint — 确认全部测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- 所有属性测试均为必须任务（非可选），每个属性测试必须运行至少 100 次迭代 (`@settings(max_examples=100)`)
- 每个属性测试必须包含注释标注：`# Feature: smartclaw-p2a-production-services, Property {N}: {title}`
- 属性测试使用 hypothesis 库，API 网关测试使用 httpx + FastAPI TestClient，异步测试使用 pytest-asyncio
- 所有 20 个需求（Requirements 1–20）均被实现和测试任务覆盖
- 所有 19 个正确性属性（Properties 1–19）均有对应的属性测试任务
- 实现按依赖顺序推进：配置 → Hook 系统 → 诊断事件总线 → OTEL Traces → API 网关 → Agent Graph 集成 → 向后兼容
- 每个主要模块后设置 checkpoint 确保增量验证
- Python 为实现语言（与设计文档一致）
