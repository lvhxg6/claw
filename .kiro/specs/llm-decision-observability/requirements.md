# 需求文档：LLM 决策可观测性（Decision Trace）

## 简介

SmartClaw 当前的可观测性基础设施（Hooks、Diagnostic Bus、OTEL Tracing、Debug UI）能够展示"发生了什么"（调用了哪个工具、耗时多少），但无法回答"为什么"——LLM 的推理内容、工具选择的上下文、Supervisor 路由决策的依据均不可见。

本特性引入 **Decision Trace** 系统，在每次 LLM 调用和工具执行时捕获决策上下文（输入摘要、决策类型、推理内容、工具选择理由），并通过 Debug UI 中新增的"🧠 Decisions"标签页以时间线形式展示，使开发者能够直观理解 Agent 的每一步决策过程。

## 术语表

- **Decision_Trace_Collector**：决策追踪收集器，负责从 Agent 运行时捕获决策记录并存储到内存中的模块。
- **Decision_Record**：单条决策记录数据结构，包含时间戳、迭代轮次、决策类型、输入摘要、推理内容、工具调用信息等字段。
- **Decision_Type**：决策类型枚举，包括 `tool_call`（调用工具）、`final_answer`（生成最终回答）、`supervisor_route`（Supervisor 路由）。
- **Debug_UI**：SmartClaw 的 Web 调试界面（`gateway/static/index.html`），包含 Chat 面板和 Debug 面板。
- **Decision_Tab**：Debug UI 中新增的"🧠 Decisions"标签页，用于展示决策时间线。
- **Decision_SSE_Endpoint**：新增的 SSE 端点，用于将决策记录实时推送到 Debug UI。
- **Reasoning_Content**：LLM 响应中的推理/思考内容，即 LLM 解释其决策的文本。
- **Input_Summary**：发送给 LLM 的输入上下文摘要，包括用户消息和最近的工具结果。
- **Diagnostic_Bus**：SmartClaw 的模块级单例发布/订阅事件总线（`observability/diagnostic_bus.py`）。
- **Hook_Registry**：SmartClaw 的生命周期钩子注册表（`hooks/registry.py`），支持 8 个钩子点。
- **Reasoning_Node**：Agent 图中的推理节点（`agent/nodes.py`），负责调用 LLM。
- **Action_Node**：Agent 图中的动作节点（`agent/nodes.py`），负责执行工具调用。
- **Supervisor_Node**：多 Agent 协调器中的 Supervisor 节点（`agent/multi_agent.py`），负责路由决策。

## 需求

### 需求 1：Decision_Record 数据结构定义

**用户故事：** 作为开发者，我希望有一个标准化的决策记录数据结构，以便统一表示 LLM 的每一步决策信息。

#### 验收标准

1. THE Decision_Record SHALL 包含以下必填字段：timestamp（ISO 8601 UTC 时间戳）、iteration（迭代轮次，整数）、decision_type（Decision_Type 枚举值）、input_summary（输入上下文摘要，字符串，最大 512 字符）、reasoning（推理内容，字符串，最大 2048 字符）
2. THE Decision_Record SHALL 包含以下可选字段：tool_calls（工具调用列表，每项包含 tool_name 和 tool_args）、target_agent（Supervisor 路由目标 Agent 名称）、session_key（会话标识符）
3. THE Decision_Record SHALL 提供 to_dict() 方法将记录序列化为 JSON 兼容的字典
4. THE Decision_Record SHALL 提供 from_dict() 类方法从字典反序列化为 Decision_Record 实例
5. FOR ALL 合法的 Decision_Record 实例，执行 from_dict(record.to_dict()) SHALL 产生与原始实例等价的对象（往返一致性）

### 需求 2：LLM 调用决策捕获

**用户故事：** 作为开发者，我希望在每次 LLM 调用后自动捕获决策信息，以便了解 LLM 为什么选择调用工具或生成最终回答。

#### 验收标准

1. WHEN Reasoning_Node 完成一次 LLM 调用且 LLM 返回工具调用时，THE Decision_Trace_Collector SHALL 创建一条 decision_type 为 `tool_call` 的 Decision_Record
2. WHEN Reasoning_Node 完成一次 LLM 调用且 LLM 返回最终回答时，THE Decision_Trace_Collector SHALL 创建一条 decision_type 为 `final_answer` 的 Decision_Record
3. THE Decision_Trace_Collector SHALL 从 LLM 响应的 AIMessage.content 中提取 Reasoning_Content 并填入 Decision_Record 的 reasoning 字段
4. THE Decision_Trace_Collector SHALL 从发送给 LLM 的消息列表中提取最近一条用户消息或工具结果作为 Input_Summary
5. WHEN LLM 返回工具调用时，THE Decision_Trace_Collector SHALL 将所有 tool_calls（包含 tool_name 和 tool_args）记录到 Decision_Record 的 tool_calls 字段
6. IF Reasoning_Node 调用 LLM 失败，THEN THE Decision_Trace_Collector SHALL 不创建 Decision_Record（仅在成功调用时捕获）

### 需求 3：Supervisor 路由决策捕获

**用户故事：** 作为开发者，我希望在 Supervisor 做出路由决策时自动捕获决策信息，以便了解为什么选择了特定的 Agent。

#### 验收标准

1. WHEN Supervisor_Node 完成路由决策且选择了一个目标 Agent 时，THE Decision_Trace_Collector SHALL 创建一条 decision_type 为 `supervisor_route` 的 Decision_Record
2. THE Decision_Trace_Collector SHALL 将 Supervisor LLM 响应的原始 JSON 内容记录到 Decision_Record 的 reasoning 字段
3. THE Decision_Trace_Collector SHALL 将路由目标 Agent 名称记录到 Decision_Record 的 target_agent 字段
4. WHEN Supervisor_Node 决定任务完成（agent="done"）时，THE Decision_Trace_Collector SHALL 创建一条 decision_type 为 `final_answer` 的 Decision_Record，并将 Supervisor 的合成回答记录到 reasoning 字段

### 需求 4：决策记录存储与查询

**用户故事：** 作为开发者，我希望决策记录按会话存储并支持查询，以便在 Debug UI 中按需展示。

#### 验收标准

1. THE Decision_Trace_Collector SHALL 在内存中按 session_key 分组存储 Decision_Record 列表
2. WHEN 未提供 session_key 时，THE Decision_Trace_Collector SHALL 使用默认键 "__default__" 进行存储
3. THE Decision_Trace_Collector SHALL 提供 get_decisions(session_key) 方法返回指定会话的所有 Decision_Record 列表，按时间戳升序排列
4. THE Decision_Trace_Collector SHALL 提供 clear(session_key) 方法清除指定会话的所有决策记录
5. THE Decision_Trace_Collector SHALL 对每个 session_key 最多保留 200 条 Decision_Record，超出时丢弃最早的记录


### 需求 5：决策事件通过 Diagnostic Bus 发布

**用户故事：** 作为开发者，我希望决策事件通过现有的 Diagnostic Bus 发布，以便与 OTEL Tracing 等其他可观测性组件集成。

#### 验收标准

1. WHEN Decision_Trace_Collector 创建一条新的 Decision_Record 时，THE Decision_Trace_Collector SHALL 通过 Diagnostic_Bus 发布一个 `decision.captured` 事件，payload 为该 Decision_Record 的 to_dict() 结果
2. THE Diagnostic_Bus SHALL 支持 `decision.captured` 作为合法的事件类型
3. IF Diagnostic_Bus 发布失败，THEN THE Decision_Trace_Collector SHALL 记录错误日志并继续正常运行（不影响 Agent 主流程）

### 需求 6：决策事件 SSE 实时推送

**用户故事：** 作为开发者，我希望决策事件能通过 SSE 实时推送到 Debug UI，以便在调试时实时观察 LLM 的决策过程。

#### 验收标准

1. THE Decision_SSE_Endpoint SHALL 在路径 `/api/debug/decision-events` 上提供 SSE 流
2. WHEN Decision_Trace_Collector 发布 `decision.captured` 事件时，THE Decision_SSE_Endpoint SHALL 将该事件以 JSON 格式推送到所有已连接的 SSE 客户端
3. WHILE 无决策事件产生超过 15 秒时，THE Decision_SSE_Endpoint SHALL 发送一个 `{"ping": true}` 心跳消息以保持连接
4. IF SSE 客户端断开连接，THEN THE Decision_SSE_Endpoint SHALL 清理该客户端的事件队列资源
5. THE Decision_SSE_Endpoint SHALL 为每个客户端维护最大容量为 100 的事件队列，队列满时丢弃新事件

### 需求 7：Debug UI 决策时间线标签页

**用户故事：** 作为开发者，我希望在 Debug UI 中看到一个"🧠 Decisions"标签页，以时间线形式展示 LLM 的决策过程。

#### 验收标准

1. THE Debug_UI SHALL 在 Debug 面板的标签栏中新增一个"🧠 Decisions"标签页，位于"🪝 Hooks"标签页之后
2. THE Decision_Tab SHALL 通过 SSE 连接 Decision_SSE_Endpoint 实时接收决策事件
3. WHEN 收到一条 decision_type 为 `tool_call` 的决策事件时，THE Decision_Tab SHALL 以卡片形式展示：时间戳、迭代轮次、"→ Tool Call" 标签、Input_Summary、工具名称和参数、Reasoning_Content
4. WHEN 收到一条 decision_type 为 `final_answer` 的决策事件时，THE Decision_Tab SHALL 以卡片形式展示：时间戳、迭代轮次、"→ Final Answer" 标签、Input_Summary、Reasoning_Content
5. WHEN 收到一条 decision_type 为 `supervisor_route` 的决策事件时，THE Decision_Tab SHALL 以卡片形式展示：时间戳、迭代轮次、"→ Route: {target_agent}" 标签、Reasoning_Content
6. THE Decision_Tab SHALL 按时间倒序排列决策卡片（最新的在最上方）
7. THE Decision_Tab SHALL 在无决策事件时显示占位文本"等待决策事件..."
8. THE Decision_Tab SHALL 最多展示 100 条决策卡片，超出时移除最早的卡片

### 需求 8：决策时间线卡片视觉区分

**用户故事：** 作为开发者，我希望不同类型的决策卡片有明显的视觉区分，以便快速识别决策类型。

#### 验收标准

1. THE Decision_Tab SHALL 为 `tool_call` 类型的决策卡片使用绿色系边框（与现有 tool-call 消息风格一致，边框色 #2d4a2d）
2. THE Decision_Tab SHALL 为 `final_answer` 类型的决策卡片使用蓝色系边框（与现有 assistant 消息风格一致，边框色 #2d2d4a）
3. THE Decision_Tab SHALL 为 `supervisor_route` 类型的决策卡片使用紫色系边框（边框色 #4a2d4a）
4. THE Decision_Tab SHALL 在每张决策卡片的 Reasoning_Content 区域支持点击展开/折叠，默认折叠状态下最多显示 3 行

### 需求 9：Decision Record 序列化往返一致性

**用户故事：** 作为开发者，我希望 Decision_Record 的序列化和反序列化是可靠的，以便在 SSE 传输和存储过程中不丢失数据。

#### 验收标准

1. FOR ALL 合法的 Decision_Record 实例，THE Decision_Record 的 to_dict() 输出 SHALL 为合法的 JSON 可序列化字典（所有值为 str、int、float、bool、None、list 或 dict 类型）
2. FOR ALL 合法的 Decision_Record 实例，执行 json.loads(json.dumps(record.to_dict())) SHALL 产生与 record.to_dict() 相同的字典
3. FOR ALL 合法的 to_dict() 输出字典，执行 Decision_Record.from_dict(d).to_dict() SHALL 产生与原始字典 d 相同的结果
4. WHEN from_dict() 接收到缺少必填字段的字典时，THE Decision_Record SHALL 抛出 ValueError 并包含缺失字段名称的描述

### 需求 10：决策捕获对 Agent 主流程的性能影响控制

**用户故事：** 作为开发者，我希望决策捕获不会显著影响 Agent 的正常运行性能。

#### 验收标准

1. THE Decision_Trace_Collector SHALL 在 Reasoning_Node 和 Supervisor_Node 的现有执行流程中同步捕获决策数据，捕获逻辑本身不引入额外的异步 I/O 操作
2. IF Decision_Trace_Collector 在捕获过程中发生异常，THEN THE Decision_Trace_Collector SHALL 记录错误日志并允许 Agent 主流程继续执行（不中断 Agent 运行）
3. THE Decision_Trace_Collector SHALL 将 Input_Summary 截断到最大 512 字符，将 Reasoning_Content 截断到最大 2048 字符，以控制内存占用

### 需求 11：REST API 查询决策记录

**用户故事：** 作为开发者，我希望能通过 REST API 查询指定会话的决策记录，以便在非实时场景下回顾决策历史。

#### 验收标准

1. THE Gateway SHALL 在路径 `GET /api/sessions/{session_key}/decisions` 上提供决策记录查询端点
2. WHEN 请求指定 session_key 的决策记录时，THE Gateway SHALL 返回该会话的所有 Decision_Record 列表，格式为 JSON 数组
3. WHEN 请求的 session_key 不存在决策记录时，THE Gateway SHALL 返回空数组 `[]`
4. THE Gateway SHALL 返回的 Decision_Record 列表按时间戳升序排列
