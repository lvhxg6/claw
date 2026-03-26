# 需求文档：统一 Agent 运行时 + Gateway 功能对齐

## 简介

当前 SmartClaw 的 CLI 模式和 Gateway（API）模式存在能力不一致的问题。CLI 拥有完整的 P1 功能集（Skills 加载、Sub-Agent 工具、AutoSummarizer 上下文压缩、System Prompt 含 skills 描述注入），而 Gateway 仅初始化了 8 个基础系统工具，缺少上述所有高级能力以及 MCP 工具集成。

本需求通过抽取共享初始化函数 `setup_agent_runtime(settings)` 返回 `AgentRuntime` 对象，使 CLI 和 Gateway 共用同一套初始化逻辑，保证能力完全一致。同时增加请求级模型切换能力，允许 API 调用方在单次请求中临时指定不同模型。

## 术语表

- **AgentRuntime**: 封装 Agent 运行所需全部资源的对象，包含已编译的 LangGraph、ToolRegistry、MemoryStore、AutoSummarizer、MCPManager、System Prompt 等
- **Gateway**: SmartClaw 的 FastAPI HTTP API 服务，提供 `/api/chat` 和 `/api/chat/stream` 等端点
- **CLI**: SmartClaw 的命令行交互界面，通过 `python -m smartclaw.cli` 启动
- **ToolRegistry**: 工具注册中心，管理所有 BaseTool 实例的注册、发现和获取
- **SkillsLoader**: YAML/Markdown 技能定义的发现和动态加载器
- **SkillsRegistry**: 技能注册管理器，将技能提供的工具注册到 ToolRegistry
- **AutoSummarizer**: 基于 LLM 的自动对话摘要和上下文压缩组件
- **MemoryStore**: 基于 SQLite 的异步对话历史持久化存储
- **SpawnSubAgentTool**: 将子任务委派给子 Agent 执行的 LangChain BaseTool
- **System_Prompt**: 注入给 LLM 的系统提示词，包含工具使用指南和 skills 描述
- **Model_Override**: 请求级模型切换，允许单次 API 请求临时使用不同的 LLM 模型
- **ChatRequest**: Gateway 的 Pydantic 请求模型，定义 `/api/chat` 的输入结构
- **setup_agent_runtime**: 共享初始化函数，CLI 和 Gateway 统一调用以构建 AgentRuntime
- **MCPManager**: MCP 协议管理器，管理 MCP 服务器连接和工具调用
- **MCPToolBridge**: 将 MCP 服务器发现的工具桥接为 LangChain BaseTool 的适配器

## 需求

### 需求 1：共享 Agent 运行时初始化函数

**用户故事：** 作为开发者，我希望 CLI 和 Gateway 使用同一个初始化函数构建 Agent 运行时，以消除两个入口之间的能力差异。

#### 验收标准

1. THE setup_agent_runtime 函数 SHALL 接受 SmartClawSettings 作为输入参数，返回一个包含 graph、registry、memory_store、summarizer、system_prompt、mcp_manager 字段的 AgentRuntime 对象
2. THE setup_agent_runtime 函数 SHALL 按以下顺序初始化资源：创建 ToolRegistry 系统工具、初始化 MCPManager 并桥接 MCP 工具、加载 Skills、注册 SpawnSubAgentTool、构建 System Prompt、初始化 MemoryStore、创建 AutoSummarizer、编译 LangGraph
3. WHEN SmartClawSettings 中 skills.enabled 为 True 时，THE setup_agent_runtime 函数 SHALL 通过 SkillsLoader 和 SkillsRegistry 加载并注册所有技能工具，并生成 skills_summary 注入到 System_Prompt 中
4. WHEN SmartClawSettings 中 sub_agent.enabled 为 True 时，THE setup_agent_runtime 函数 SHALL 创建 SpawnSubAgentTool 实例并注册到 ToolRegistry 中
5. WHEN SmartClawSettings 中 memory.enabled 为 True 时，THE setup_agent_runtime 函数 SHALL 初始化 MemoryStore 并创建 AutoSummarizer 实例
6. WHEN SmartClawSettings 中 mcp.enabled 为 True 时，THE setup_agent_runtime 函数 SHALL 初始化 MCPManager，连接所有已启用的 MCP 服务器，并通过 create_mcp_tools 将发现的 MCP 工具桥接注册到 ToolRegistry 中
7. IF Skills 加载过程中发生异常，THEN THE setup_agent_runtime 函数 SHALL 记录警告日志并继续初始化其余组件，skills_summary 设为空字符串
8. IF Sub-Agent 工具创建过程中发生异常，THEN THE setup_agent_runtime 函数 SHALL 记录警告日志并继续初始化其余组件
9. IF MemoryStore 初始化过程中发生异常，THEN THE setup_agent_runtime 函数 SHALL 记录警告日志，将 memory_store 和 summarizer 设为 None，并继续初始化其余组件
10. IF MCPManager 初始化过程中发生异常，THEN THE setup_agent_runtime 函数 SHALL 记录警告日志并继续初始化其余组件，MCP 工具不可用但不影响其他工具


### 需求 2：Gateway 使用共享运行时实现功能对齐

**用户故事：** 作为 API 调用方，我希望通过 Gateway 访问与 CLI 完全一致的 Agent 能力（Skills、Sub-Agent、Memory、Summarizer、System Prompt），以获得统一的服务体验。

#### 验收标准

1. THE Gateway 的 lifespan 函数 SHALL 调用 setup_agent_runtime 函数初始化 AgentRuntime，并将其存储在 app.state 中
2. THE Gateway 的 chat 端点 SHALL 在调用 invoke 时传入 AgentRuntime 中的 system_prompt 参数
3. THE Gateway 的 chat 端点 SHALL 在调用 invoke 时传入 AgentRuntime 中的 summarizer 参数
4. THE Gateway 的 chat_stream 端点 SHALL 在调用 invoke 时传入 AgentRuntime 中的 system_prompt 和 summarizer 参数
5. WHEN Gateway 启动完成后，THE Gateway 的 health 端点 SHALL 返回的 tools_count 值与 AgentRuntime 中 ToolRegistry 的实际工具数量一致（包含 Skills 工具和 Sub-Agent 工具）

### 需求 3：CLI 使用共享运行时重构

**用户故事：** 作为开发者，我希望 CLI 入口重构为调用 setup_agent_runtime 函数，以消除与 Gateway 之间的重复初始化代码。

#### 验收标准

1. THE CLI 的 _run_agent_loop 函数 SHALL 调用 setup_agent_runtime 函数获取 AgentRuntime 对象，替代现有的内联初始化逻辑
2. THE CLI SHALL 保留 --no-memory、--no-skills、--no-sub-agent 命令行参数的功能，通过在调用 setup_agent_runtime 前临时修改 SmartClawSettings 中对应的 enabled 字段实现
3. THE CLI 的 banner 输出 SHALL 从 AgentRuntime 对象中读取工具数量、skills 状态、sub-agent 状态和 memory 状态，保持与重构前一致的显示内容
4. THE CLI 的交互循环 SHALL 使用 AgentRuntime 中的 graph、memory_store、summarizer 和 system_prompt 调用 invoke 函数

### 需求 4：请求级模型切换

**用户故事：** 作为 API 调用方，我希望在单次请求中指定不同的 LLM 模型，以便根据任务复杂度灵活选择模型。

#### 验收标准

1. THE ChatRequest 模型 SHALL 包含一个可选的 model 字段，类型为 str，默认值为 None
2. WHEN ChatRequest 的 model 字段为 None 或空字符串时，THE chat 端点 SHALL 使用 AgentRuntime 中预编译的默认 graph 处理请求
3. WHEN ChatRequest 的 model 字段包含有效的模型引用（格式为 "provider/model"）时，THE chat 端点 SHALL 使用该模型引用临时创建一个新的 ModelConfig，调用 build_graph 构建临时 graph，并使用该临时 graph 处理当前请求
4. THE chat_stream 端点 SHALL 与 chat 端点遵循相同的模型切换逻辑
5. WHEN ChatRequest 的 model 字段包含无法解析的模型引用时，THE chat 端点 SHALL 返回 HTTP 400 状态码和描述性错误信息
6. THE 临时创建的 graph SHALL 使用 AgentRuntime 中 ToolRegistry 的全部工具，仅替换 ModelConfig 中的 primary 模型

### 需求 5：AgentRuntime 资源生命周期管理

**用户故事：** 作为运维人员，我希望 AgentRuntime 的资源在应用关闭时被正确清理，以防止资源泄漏。

#### 验收标准

1. THE AgentRuntime 对象 SHALL 提供一个 close 异步方法，用于释放所有持有的资源
2. WHEN AgentRuntime 的 close 方法被调用时，THE AgentRuntime SHALL 关闭 MemoryStore 的数据库连接（如果 MemoryStore 已初始化）和 MCPManager 的所有服务器连接（如果 MCPManager 已初始化）
3. THE Gateway 的 lifespan 函数 SHALL 在 shutdown 阶段调用 AgentRuntime 的 close 方法
4. THE CLI SHALL 在交互循环结束后调用 AgentRuntime 的 close 方法
5. IF close 方法执行过程中发生异常，THEN THE AgentRuntime SHALL 记录错误日志并继续清理其余资源，确保不抛出异常到调用方

### 需求 6：初始化一致性验证

**用户故事：** 作为开发者，我希望能够验证 CLI 和 Gateway 初始化后的 Agent 能力完全一致，以确保功能对齐目标达成。

#### 验收标准

1. WHEN 使用相同的 SmartClawSettings 调用 setup_agent_runtime 时，THE 返回的 AgentRuntime 中 ToolRegistry 注册的工具名称集合 SHALL 在 CLI 和 Gateway 之间完全一致
2. WHEN 使用相同的 SmartClawSettings 调用 setup_agent_runtime 时，THE 返回的 AgentRuntime 中的 system_prompt 内容 SHALL 在 CLI 和 Gateway 之间完全一致
3. THE AgentRuntime 对象 SHALL 提供一个 tool_names 属性，返回当前注册的所有工具名称列表（已排序），便于一致性比对
