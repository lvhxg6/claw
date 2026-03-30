# SmartClaw 功能特性与技术架构

## 1. 项目定位

SmartClaw 是一个工程生产级 AI Agent 框架，面向浏览器自动化、Web 调研、RPA 等场景。核心设计理念是：**可观测、可审计、可约束、可扩展**。

---

## 2. 核心功能特性总览

### 2.1 多 LLM Provider 支持与动态切换

| 能力 | 说明 |
|------|------|
| 多 Provider 内置 | 内置 OpenAI、Anthropic、Kimi（月之暗面）、GLM 四大 Provider |
| 配置驱动扩展 | 通过 `ProviderSpec` 声明式注册自定义 Provider（YAML 配置即可接入新 LLM） |
| `provider/model` 统一引用 | 所有模型以 `kimi/kimi-k2.5`、`openai/gpt-4o` 格式统一引用 |
| 动态 importlib 加载 | 通过 `class_path` 动态导入 LangChain ChatModel 类，无需硬编码 |
| 运行时模型切换 | 通过 Gateway API `/api/models/switch` 或 `runtime.switch_model()` 实时切换主模型 |
| 可用模型查询 | `runtime.get_available_models()` 返回当前可用的所有模型列表 |

### 2.2 LLM Fallback Chain（故障自动切换）

| 能力 | 说明 |
|------|------|
| 多级 Fallback | primary → fallbacks 列表，按优先级逐个尝试 |
| 错误分类引擎 | `classify_error()` 自动识别 rate_limit / timeout / auth / format_error 等故障类型 |
| 指数退避 Cooldown | `CooldownTracker` 按错误次数计算指数退避冷却时间，避免反复冲击故障 Provider |
| AuthProfile 轮转 | 同一 Provider 支持多个 API Key（AuthProfile），Key 级别轮转后再切换 Provider |
| Session Sticky | 可选的会话粘性策略，优先使用上次成功的 AuthProfile |
| Cooldown 持久化 | Cooldown 状态可持久化到 MemoryStore，跨重启恢复 |
| 两阶段候选构建 | `_build_two_stage_candidates()` 先尝试同 Provider 不同 Key，再跨 Provider 切换 |

### 2.3 上下文自动压缩（多级 Context Compaction）

SmartClaw 实现了 **L1 → L2 → L3 → L4** 四级上下文压缩体系：

| 层级 | 组件 | 策略 |
|------|------|------|
| L1 | `ToolResultGuard` | 工具返回结果即时截断（head + tail 保留，中间省略） |
| L2 | `SessionPruner` | 会话级 ToolMessage 双阈值修剪（soft-trim 50% / hard-clear 70%） |
| L3 | `AutoSummarizer` | LLM 驱动的对话摘要（消息数 + token 百分比双阈值触发） |
| L4 | Multi-stage Compaction | 超长上下文分块摘要 → 合并 → 溢出恢复 |

关键设计：
- `SessionPruner` 保护 head/tail 消息不被修剪，仅修剪中间 ToolMessage
- `AutoSummarizer` 支持独立的 `compaction_model` 配置（可用小模型做摘要降低成本）
- 标识符保留策略（`identifier_policy`）：strict / custom / off，确保压缩后关键标识不丢失
- `ContextEngine` 抽象接口统一管理上下文生命周期（bootstrap → ingest → assemble → compact → dispose）

### 2.4 Tools 工具系统

#### 2.4.1 系统工具（9 个）

| 工具 | 功能 |
|------|------|
| `read_file` | 读取文件内容（受 PathPolicy 约束） |
| `write_file` | 写入文件（受 PathPolicy 约束） |
| `edit_file` | 精确编辑文件（行级替换） |
| `append_file` | 追加文件内容 |
| `list_directory` | 列出目录结构 |
| `shell` | 执行 Shell 命令（deny patterns 安全过滤） |
| `web_search` | Web 搜索（Tavily） |
| `web_fetch` | 抓取网页内容 |
| `ask_clarification` | 向用户提出澄清问题（支持预定义选项） |

#### 2.4.2 浏览器工具（15+ 个）

基于 Playwright + CDP 的完整浏览器自动化工具集：
- 导航、点击、输入、截图
- Accessibility Tree 快照（页面语义理解）
- Tab 管理、元素等待
- CDP 协议直连

#### 2.4.3 工具注册中心

`ToolRegistry` 提供统一的工具生命周期管理：
- 注册 / 注销 / 查询 / 合并
- 系统工具 + MCP 工具 + Skills 工具统一注册
- 工具名去重与冲突检测

### 2.5 MCP 协议支持

| 能力 | 说明 |
|------|------|
| 双传输协议 | 支持 stdio 和 Streamable HTTP 两种 MCP 传输方式 |
| 自动传输检测 | `detect_transport()` 根据配置自动判断传输类型 |
| 动态工具桥接 | MCP Server 发现的工具自动桥接为 LangChain BaseTool |
| 并发连接管理 | `MCPManager` 并发初始化多个 MCP Server |
| 优雅关闭 | in-flight 调用计数 + drain 等待，确保关闭时不丢失调用 |
| 环境变量合并 | 支持 `env_file` + `env` 映射，灵活配置 MCP Server 环境 |
| 错误隔离 | 单个 MCP Server 连接失败不影响其他 Server |

### 2.6 Skills 技能系统

| 能力 | 说明 |
|------|------|
| 三种格式 | YAML 格式（Python 函数工具）、SKILL.md 格式（Markdown 提示词技能）、Native Command（shell/script/exec） |
| 三级目录优先级 | workspace > global > builtin |
| scripts/ 自动发现 | SKILL.md 目录下的 `scripts/` 自动注册为可用命令 |
| 热重载 | `SkillsWatcher` 基于 watchdog 监听文件变更，自动重新加载 |
| 版本追踪 | 每次重载递增版本号，支持变更检测 |
| 防抖机制 | 可配置的 debounce 时间，避免频繁重载 |

### 2.7 Hook 生命周期钩子

8 个标准 Hook 点覆盖 Agent 完整生命周期：

| Hook Point | 触发时机 |
|------------|----------|
| `tool:before` | 工具调用前 |
| `tool:after` | 工具调用后 |
| `agent:start` | Agent 开始处理用户消息 |
| `agent:end` | Agent 处理完成 |
| `llm:before` | LLM 调用前 |
| `llm:after` | LLM 调用后 |
| `session:start` | 会话开始 |
| `session:end` | 会话结束 |

设计特点：
- 异步 Handler，顺序执行
- 错误隔离：单个 Handler 异常不影响其他 Handler
- 丰富的事件数据：每个 Hook 事件携带完整上下文（工具名、参数、结果、耗时等）
- JSON 序列化支持：`to_dict()` / `from_dict()` 支持事件持久化与回放

### 2.8 可观测性（Observability）

#### 2.8.1 Diagnostic Event Bus

事件驱动的诊断总线，支持以下事件类型：
- `tool.executed` — 工具执行完成
- `llm.called` — LLM 调用完成
- `agent.run` — Agent 调用生命周期（start / end）
- `session.started` / `session.ended` — 会话生命周期
- `config.reloaded` — 配置热重载
- `decision.captured` — 决策记录捕获
- `plan.created` / `plan.updated` — 编排计划事件
- `dispatch.*` — 任务分发事件
- `governance.approval_required` — 治理审批事件
- `schema.validation` — Schema 校验事件

#### 2.8.2 OpenTelemetry 分布式追踪

- `OTELTracingService` 集成 OpenTelemetry SDK
- 支持 OTLP gRPC / HTTP 两种导出协议
- 自动创建 `agent.invoke` → `llm.call` → `tool.execute.{name}` 层级 Span
- 敏感数据自动脱敏（`redact_attributes()`）

#### 2.8.3 结构化日志

- 基于 structlog 的结构化日志
- 支持 console / JSON 两种输出格式
- 组件级日志标签（`component="xxx"`）

### 2.9 可审计性（Auditability）

#### 2.9.1 Decision Record（决策记录）

每一步 LLM 决策都被记录为不可变的 `DecisionRecord`：

| 字段 | 说明 |
|------|------|
| `timestamp` | UTC 时间戳 |
| `iteration` | 迭代轮次 |
| `decision_type` | tool_call / final_answer / supervisor_route |
| `input_summary` | 输入摘要（≤512 字符） |
| `reasoning` | 推理过程（≤2048 字符） |
| `tool_calls` | 工具调用详情 |
| `target_agent` | 路由目标 Agent |
| `session_key` | 会话标识 |

#### 2.9.2 Decision Collector

- 按 session_key 分组存储决策记录
- 每个 session 最多保留 200 条记录（自动淘汰旧记录）
- 通过 Diagnostic Bus 发布 `decision.captured` 事件
- 支持 SSE 实时推送到 Debug UI

### 2.10 可约束性（Governance & Security）

#### 2.10.1 路径安全策略（PathPolicy）

- 白名单 / 黑名单 glob 模式匹配
- 默认拒绝敏感路径：`~/.ssh/**`、`~/.aws/**`、`/etc/shadow` 等
- 黑名单优先评估
- 符号链接解析后再匹配（防绕过）
- 安全事件日志记录

#### 2.10.2 Capability Pack 治理

| 治理能力 | 说明 |
|----------|------|
| 工具白名单/黑名单 | `allowed_tools` / `denied_tools` 限制可用工具范围 |
| Step 白名单/优先级 | `allowed_steps` / `preferred_steps` 约束编排步骤 |
| 审批机制 | `approval_required` 执行前需用户显式批准 |
| 结构化输出校验 | `schema_enforced` + JSON Schema 校验最终输出 |
| 重试策略 | `max_task_retries` / `max_schema_retries` / `retry_on_error` |
| 并发限制 | `concurrency_limits` 按工具组限制并发数 |
| 重复错误检测 | `repeated_error_threshold` 检测重复错误并触发 guardrail |

#### 2.10.3 敏感数据脱敏（Redaction）

- API Key 模式检测（`sk-`、`key-`、`token-` 前缀）
- Email 模式检测
- 敏感环境变量名检测（`API_KEY`、`SECRET`、`PASSWORD` 等）
- OTEL Span 属性自动脱敏
- 字符串长度截断保护

### 2.11 Agent 编排体系

#### 2.11.1 双模式执行引擎

| 模式 | 说明 |
|------|------|
| `classic` | 标准 ReAct 循环（think → act → observe） |
| `orchestrator` | 多阶段动态编排（plan → dispatch → execute → review → synthesize） |
| `auto` | ModeRouter 自动路由（基于关键词启发式 + 场景类型 + 任务画像） |

#### 2.11.2 Sub-Agent 子代理

- LangGraph SubGraph 实现
- 深度限制（`max_depth`，默认 3 层）
- 并发控制（`max_concurrent`，默认 5 个）
- 并发超时保护
- `EphemeralStore` 临时消息存储（自动压缩）
- 作为 LangChain Tool 暴露给主 Agent

#### 2.11.3 Multi-Agent 多代理协同

- Supervisor 模式：一个 Supervisor Agent 协调多个 Worker Agent
- 角色配置：每个 Agent 可独立配置 model、system_prompt、tools
- 路由决策：Supervisor 决定下一步由哪个 Agent 执行
- 结果聚合：自动合成多 Agent 的部分结果

#### 2.11.4 Loop Detector 循环检测

- 基于 hash 的滑动窗口检测
- 工具调用 SHA-256 指纹
- 三级状态：OK → WARN → STOP
- 可配置窗口大小和阈值

### 2.12 记忆系统（Memory）

| 能力 | 说明 |
|------|------|
| SQLite 持久化 | 基于 aiosqlite 的异步持久化存储 |
| 跨会话记忆 | 按 session_key 隔离的完整消息历史 |
| 对话摘要 | LLM 驱动的自动摘要，双阈值触发 |
| 会话管理 | 创建 / 列表 / 删除 / 清空会话 |
| 附件管理 | 上传附件的元数据与提取文本持久化 |
| Cooldown 状态持久化 | Fallback Chain 的冷却状态跨重启恢复 |
| Fact Extraction | LLM 驱动的事实抽取（类别、置信度、去重、裁剪） |
| MEMORY.md 支持 | 加载 MEMORY.md 文件作为长期记忆上下文 |

### 2.13 配置热重载

| 组件 | 说明 |
|------|------|
| `ConfigWatcher` | 基于 watchdog 监听 config.yaml 变更，自动重载并校验 |
| `SkillsWatcher` | 监听 skills 目录变更，自动重新加载技能 |
| 防抖机制 | 可配置的 debounce 时间，避免频繁触发 |
| 配置 diff | 变更前后配置对比，仅应用差异部分 |
| 校验保护 | 新配置校验失败时保留旧配置，不会导致运行时崩溃 |

### 2.14 API Gateway

基于 FastAPI 的 HTTP API 网关：

| 端点 | 功能 |
|------|------|
| `/api/chat` | 对话接口（支持 SSE 流式） |
| `/api/sessions` | 会话管理（列表、历史、摘要） |
| `/api/tools` | 工具列表查询 |
| `/api/models` | 模型查询与切换 |
| `/api/uploads` | 文件上传与附件管理 |
| `/api/capability-packs` | Capability Pack 查询 |
| `/api/health` | 健康检查与就绪探针 |
| `/api/debug/hook-events` | Hook 事件 SSE 流（Debug UI） |
| `/api/debug/decision-events` | 决策事件 SSE 流（Debug UI） |
| `/api/debug/execution-events` | 编排执行事件 SSE 流（Debug UI） |

### 2.15 文件上传与文档分析

| 能力 | 说明 |
|------|------|
| 多格式支持 | TXT、Markdown、JSON、YAML、CSV、PDF、DOCX、XLSX、PNG、JPEG、WebP |
| 文本提取链路 | 每种格式对应独立的 Extractor（PlainText、PDF、DOCX、XLSX、CSV、JSON/YAML） |
| 图片分析 | 支持 OCR（Tesseract）和 Vision 模型两种模式 |
| 安全限制 | 文件大小限制、每会话文件数限制、媒体类型白名单 |
| SHA-256 校验 | 上传文件完整性校验 |

### 2.16 Bootstrap 引导系统

| 文件 | 用途 |
|------|------|
| `SOUL.md` | Agent 人格与行为准则 |
| `USER.md` | 用户上下文与偏好 |
| `TOOLS.md` | 工具使用指南与约束 |

三级目录优先级：workspace > global，支持 `PromptComposer` 结构化组装到系统提示词中。

### 2.17 Clarification 交互式澄清

- Agent 信息不足时可主动向用户提问
- 支持预定义选项（快速选择）
- 通过 `AgentState.clarification_request` 中断执行流
- Capability Pack 审批也复用此机制

---

## 3. 技术架构图

### 3.1 系统总体架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SmartClaw 系统架构                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────────────────┐ │
│  │   CLI 入口   │   │ API Gateway  │   │          Debug UI (SSE)             │ │
│  │  cli.py      │   │  FastAPI     │   │  hook-events / decision-events /    │ │
│  │              │   │  /api/chat   │   │  execution-events                   │ │
│  └──────┬───────┘   │  /api/tools  │   └──────────────────────────────────────┘ │
│         │           │  /api/models │                                             │
│         │           │  /api/upload │                                             │
│         │           └──────┬───────┘                                             │
│         └────────┬─────────┘                                                     │
│                  ▼                                                                │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                        AgentRuntime (运行时核心)                           │   │
│  │                                                                           │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │   │
│  │  │ ModeRouter  │  │PromptComposer│  │ GraphFactory │  │ ModelSwitch   │  │   │
│  │  │ auto/classic│  │ SOUL+USER+   │  │ classic /    │  │ 运行时切换     │  │   │
│  │  │ /orchestr.  │  │ TOOLS+Skills │  │ orchestrator │  │               │  │   │
│  │  └─────────────┘  └──────────────┘  └─────────────┘  └───────────────┘  │   │
│  └───────────────────────────────┬───────────────────────────────────────────┘   │
│                                  ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                     Agent 编排层 (LangGraph StateGraph)                    │   │
│  │                                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │   │
│  │  │                    Classic Mode (ReAct)                             │  │   │
│  │  │     User → [Reason Node] → [Action Node] → [Observe] → Loop       │  │   │
│  │  └─────────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │   │
│  │  │                 Orchestrator Mode (Dynamic)                         │  │   │
│  │  │  Plan → Dispatch → Execute → Review → [Replan?] → Synthesize      │  │   │
│  │  │    │                  │                                             │  │   │
│  │  │    ▼                  ▼                                             │  │   │
│  │  │  LLM Planner    Batch Workers (并发)                                │  │   │
│  │  └─────────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐    │   │
│  │  │  Sub-Agent   │  │ Multi-Agent  │  │     Loop Detector            │    │   │
│  │  │  SubGraph    │  │ Supervisor   │  │  hash 滑动窗口 + 阈值检测     │    │   │
│  │  │  深度/并发控制 │  │ 角色路由协同  │  │                              │    │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                                │
│                  ┌───────────────┼───────────────┐                               │
│                  ▼               ▼               ▼                               │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                          LLM Provider 层                                  │   │
│  │                                                                           │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐     │   │
│  │  │                    FallbackChain                                  │     │   │
│  │  │  Primary ──► Fallback 1 ──► Fallback 2 ──► ... ──► Exhausted    │     │   │
│  │  │     │            │              │                                │     │   │
│  │  │     ▼            ▼              ▼                                │     │   │
│  │  │  CooldownTracker (指数退避)  AuthProfile 轮转                    │     │   │
│  │  └──────────────────────────────────────────────────────────────────┘     │   │
│  │                                                                           │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐            │   │
│  │  │   OpenAI   │ │ Anthropic  │ │    Kimi    │ │    GLM     │  + Custom  │   │
│  │  │  ChatOpenAI│ │ChatAnthropic│ │ (月之暗面) │ │ (智谱)     │  Provider  │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘            │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                                │
│                  ┌───────────────┼───────────────┐                               │
│                  ▼               ▼               ▼                               │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                          工具与能力层                                      │   │
│  │                                                                           │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │  │   ToolRegistry   │  │   MCPManager     │  │   SkillsRegistry      │  │   │
│  │  │   (统一注册中心)  │  │  stdio + HTTP    │  │  YAML/SKILL.md/Native │  │   │
│  │  │                  │  │  动态工具桥接     │  │  热重载 + 版本追踪     │  │   │
│  │  ├──────────────────┤  └──────────────────┘  └────────────────────────┘  │   │
│  │  │ 系统工具 (9个)   │                                                     │   │
│  │  │ read/write/edit  │  ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │  │ shell/search     │  │  Browser Engine  │  │  Capability Packs     │  │   │
│  │  │ fetch/clarify    │  │  Playwright+CDP  │  │  治理策略 + Step 约束  │  │   │
│  │  │ append/list_dir  │  │  A11y Snapshot   │  │  审批 + Schema 校验   │  │   │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                                │
│                  ┌───────────────┼───────────────┐                               │
│                  ▼               ▼               ▼                               │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                       上下文与记忆层                                       │   │
│  │                                                                           │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐     │   │
│  │  │              ContextEngine (上下文生命周期管理)                    │     │   │
│  │  │  bootstrap → ingest → assemble → after_turn → compact → dispose │     │   │
│  │  └──────────────────────────────────────────────────────────────────┘     │   │
│  │                                                                           │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐     │   │
│  │  │              四级上下文压缩 (L1 → L2 → L3 → L4)                  │     │   │
│  │  │  L1: ToolResultGuard (即时截断)                                   │     │   │
│  │  │  L2: SessionPruner (soft-trim / hard-clear)                      │     │   │
│  │  │  L3: AutoSummarizer (LLM 摘要, 双阈值触发)                       │     │   │
│  │  │  L4: Multi-stage Compaction (分块摘要 + 合并 + 溢出恢复)          │     │   │
│  │  └──────────────────────────────────────────────────────────────────┘     │   │
│  │                                                                           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐    │   │
│  │  │ MemoryStore  │  │FactExtractor │  │    Artifact Store            │    │   │
│  │  │ SQLite 持久化 │  │ 事实抽取/去重 │  │  编排产物 JSON 持久化         │    │   │
│  │  │ 会话/摘要/附件│  │ 类别/置信度   │  │                              │    │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                                │
│                  ┌───────────────┼───────────────┐                               │
│                  ▼               ▼               ▼                               │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                    可观测 · 可审计 · 可约束 层                              │   │
│  │                                                                           │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │  │  Diagnostic Bus  │  │ OTEL Tracing     │  │  Decision Collector    │  │   │
│  │  │  事件驱动诊断总线 │  │ OpenTelemetry    │  │  决策记录 + 审计追踪   │  │   │
│  │  │  tool/llm/agent  │  │ gRPC/HTTP 导出   │  │  session 分组存储      │  │   │
│  │  │  session/config  │  │ 层级 Span        │  │  SSE 实时推送          │  │   │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘  │   │
│  │                                                                           │   │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │  │   Hook System    │  │   PathPolicy     │  │   Redaction            │  │   │
│  │  │  8 个生命周期钩子 │  │  路径白/黑名单   │  │  敏感数据自动脱敏      │  │   │
│  │  │  异步 + 错误隔离  │  │  符号链接解析    │  │  API Key/Email/Secret  │  │   │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                                │
│                  ┌───────────────┼───────────────┐                               │
│                  ▼               ▼               ▼                               │
│  ┌───────────────────────────────────────────────────────────────────────────┐   │
│  │                         基础设施层                                         │   │
│  │                                                                           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │ Config       │  │ Bootstrap    │  │ Upload       │  │ structlog    │  │   │
│  │  │ YAML+Pydantic│  │ SOUL/USER/   │  │ PDF/DOCX/    │  │ 结构化日志   │  │   │
│  │  │ 热重载+校验  │  │ TOOLS.md     │  │ XLSX/Image   │  │ console/JSON │  │   │
│  │  │ 环境变量覆盖 │  │              │  │ OCR/Vision   │  │              │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │   │
│  └───────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流架构

```
用户输入
  │
  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  CLI / API   │────▶│  ModeRouter  │────▶│  GraphFactory│
│  Gateway     │     │  auto 路由    │     │  构建执行图   │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          ▼                                               ▼
                 ┌─────────────────┐                            ┌─────────────────┐
                 │  Classic Mode   │                            │ Orchestrator Mode│
                 │                 │                            │                  │
                 │  ┌───────────┐  │                            │  ┌────────────┐ │
                 │  │  Reason   │  │                            │  │  Planner   │ │
                 │  │  (LLM)    │  │                            │  │  (LLM)     │ │
                 │  └─────┬─────┘  │                            │  └─────┬──────┘ │
                 │        │        │                            │        │        │
                 │  ┌─────▼─────┐  │                            │  ┌─────▼──────┐ │
                 │  │  Action   │  │                            │  │ Dispatcher  │ │
                 │  │ (Tool Call)│  │                            │  │ (Batch)    │ │
                 │  └─────┬─────┘  │                            │  └─────┬──────┘ │
                 │        │        │                            │        │        │
                 │  ┌─────▼─────┐  │                            │  ┌─────▼──────┐ │
                 │  │  Observe  │  │                            │  │  Workers   │ │
                 │  │ (Result)  │  │                            │  │ (并发执行)  │ │
                 │  └─────┬─────┘  │                            │  └─────┬──────┘ │
                 │        │        │                            │        │        │
                 │    Loop / End   │                            │  ┌─────▼──────┐ │
                 └─────────────────┘                            │  │  Reviewer  │ │
                                                                │  │ (质量检查)  │ │
                                                                │  └─────┬──────┘ │
                                                                │        │        │
                                                                │  Replan / Synth │
                                                                └─────────────────┘
                          │                                               │
                          └───────────────────────┬───────────────────────┘
                                                  ▼
                                         ┌─────────────────┐
                                         │  FallbackChain   │
                                         │  LLM 调用 + 容错 │
                                         └────────┬────────┘
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          ▼                       ▼                       ▼
                 ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
                 │  ToolRegistry   │    │  ContextEngine  │    │  MemoryStore    │
                 │  工具执行        │    │  上下文压缩      │    │  持久化存储     │
                 └─────────────────┘    └─────────────────┘    └─────────────────┘
                          │                       │                       │
                          ▼                       ▼                       ▼
                 ┌─────────────────────────────────────────────────────────────┐
                 │              Observability (可观测层)                        │
                 │  Diagnostic Bus → OTEL Tracing → Decision Collector        │
                 │  Hook System → structlog → SSE Debug Stream                │
                 └─────────────────────────────────────────────────────────────┘
```

### 3.3 LLM Fallback Chain 流程

```
用户请求
  │
  ▼
┌──────────────────────────────────────────────────────────────┐
│                     FallbackChain.execute()                   │
│                                                              │
│  Stage 1: 同 Provider AuthProfile 轮转                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐               │
│  │ kimi     │───▶│ kimi     │───▶│ kimi     │               │
│  │ key-1    │ ✗  │ key-2    │ ✗  │ key-3    │               │
│  └──────────┘    └──────────┘    └──────────┘               │
│       │                                │                     │
│       │ CooldownTracker                │ 全部冷却             │
│       │ 指数退避                        ▼                     │
│  Stage 2: 跨 Provider 切换                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐               │
│  │ openai   │───▶│anthropic │───▶│   glm    │               │
│  │ gpt-4o   │ ✗  │ claude   │ ✗  │          │               │
│  └──────────┘    └──────────┘    └──────────┘               │
│                                        │                     │
│                                        ▼                     │
│                              FallbackExhaustedError          │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 四级上下文压缩流程

```
原始消息列表 (messages)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ L1: ToolResultGuard (即时层)                             │
│ 每个 ToolMessage 返回时立即截断                           │
│ head(12000) + ... + tail(8000) ≤ 30000 chars            │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│ L2: SessionPruner (会话层, LLM 调用前)                   │
│ token 估算 > 50% context_window → soft-trim             │
│   保留 head(500) + tail(300), 中间 "..."                │
│ token 估算 > 70% context_window → hard-clear            │
│   替换为 "[tool result cleared - {name}]"               │
│ 保护: keep_head(2) + keep_recent(5) 不修剪              │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│ L3: AutoSummarizer (摘要层, turn 结束后)                 │
│ 触发条件: 消息数 ≥ threshold OR token% ≥ 70%            │
│ 动作: LLM 生成摘要 → 替换旧消息 → 保留 keep_recent      │
│ 支持独立 compaction_model (小模型降成本)                  │
│ 标识符保留策略: strict / custom / off                    │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│ L4: Multi-stage Compaction (溢出层)                      │
│ 超长上下文 → 分块(chunk_max_tokens) → 逐块摘要           │
│ → 合并摘要 → 溢出恢复(overflow_recovery)                 │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 技术选型

| 模块 | 选型 | 说明 |
|------|------|------|
| Agent 编排 | LangGraph StateGraph | 状态图驱动，支持条件路由与子图 |
| LLM 接入 | LangChain ChatModel | 统一抽象，多 Provider 适配 |
| 默认模型 | Kimi 2.5（多模态） | 月之暗面，支持 vision |
| 浏览器引擎 | Playwright + CDP | 无头浏览器 + Chrome DevTools Protocol |
| 页面理解 | Accessibility Tree | 语义化页面结构，优于 DOM 解析 |
| MCP 协议 | 官方 mcp Python SDK | stdio + Streamable HTTP 双传输 |
| 记忆存储 | SQLite (aiosqlite) | 轻量异步持久化 |
| 配置管理 | YAML + Pydantic Settings | 类型安全 + 环境变量覆盖 |
| 日志 | structlog | 结构化日志，console/JSON 双格式 |
| 分布式追踪 | OpenTelemetry | OTLP gRPC/HTTP 导出 |
| HTTP 客户端 | httpx | 异步 HTTP |
| API 网关 | FastAPI + uvicorn | 高性能异步 Web 框架 |
| SSE 流式 | sse-starlette | Server-Sent Events |
| 文件监听 | watchdog | 文件系统事件监听（热重载） |
| 包管理 | uv | 高性能 Python 包管理 |
| 测试 | pytest + hypothesis | 单元测试 + 属性测试 |
| 代码质量 | ruff + mypy | Lint + 严格类型检查 |

---

## 5. 模块依赖关系

```
                    SmartClawSettings (配置中心)
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        AgentRuntime   Gateway App   CLI Entry
              │            │
              ▼            │
    ┌─────────────────┐    │
    │  setup_agent_   │◄───┘
    │  runtime()      │
    └────────┬────────┘
             │
    ┌────────┼────────┬──────────┬──────────┬──────────┐
    ▼        ▼        ▼          ▼          ▼          ▼
ToolReg  MCPMgr  SkillsReg  MemoryStore  Bootstrap  CapPacks
    │        │        │          │          │          │
    │        │        │          ▼          │          │
    │        │        │    AutoSummarizer   │          │
    │        │        │    SessionPruner    │          │
    │        │        │    FactExtractor    │          │
    │        │        │          │          │          │
    └────────┴────────┴──────────┴──────────┴──────────┘
                           │
                           ▼
                    PromptComposer
                           │
                           ▼
                  build_graph() / build_orchestrator_graph()
                           │
                           ▼
                    FallbackChain + ProviderFactory
                           │
                           ▼
                  OpenAI / Anthropic / Kimi / GLM / Custom
```

---

## 6. 功能成熟度矩阵

| 功能模块 | 阶段 | 状态 |
|----------|------|------|
| 系统工具 (9个) | P0 | ✅ 已完成 |
| 浏览器工具 (15+个) | P0 | ✅ 已完成 |
| MCP 协议 (stdio + HTTP) | P0 | ✅ 已完成 |
| LLM Fallback Chain | P0 | ✅ 已完成 |
| 路径安全策略 | P0 | ✅ 已完成 |
| 跨会话记忆 (SQLite) | P1 | ✅ 已完成 |
| 自动摘要 (L3) | P1 | ✅ 已完成 |
| Skills 技能系统 | P1 | ✅ 已完成 |
| Sub-Agent 子代理 | P1 | ✅ 已完成 |
| Multi-Agent 协同 | P1 | ✅ 已完成 |
| Hook 生命周期 | P1 | ✅ 已完成 |
| 四级上下文压缩 | P1 | ✅ 已完成 |
| Fact Extraction | P1 | ✅ 已完成 |
| API Gateway (FastAPI) | P2A | ✅ 已完成 |
| OpenTelemetry 追踪 | P2A | ✅ 已完成 |
| Decision Record 审计 | P2A | ✅ 已完成 |
| Diagnostic Event Bus | P2A | ✅ 已完成 |
| 配置热重载 | P2A | ✅ 已完成 |
| 文件上传与文档分析 | P2A | ✅ 已完成 |
| Capability Pack 治理 | P2A | ✅ 已完成 |
| Step Registry 编排 | P2A | ✅ 已完成 |
| Orchestrator 动态编排 | P2A | ✅ 已完成 |
| Debug UI (SSE) | P2A | ✅ 已完成 |
| Bootstrap 引导系统 | P2A | ✅ 已完成 |
| 敏感数据脱敏 | P2A | ✅ 已完成 |
| Clarification 交互澄清 | P2A | ✅ 已完成 |

---

## 7. 业务场景扩展指南（零代码 / 低代码）

SmartClaw 的架构设计遵循 **"配置驱动扩展，代码只做引擎"** 的原则。面对多业务系统场景，绝大多数扩展可以通过以下 7 个扩展点完成，无需修改框架源码。

### 7.1 扩展点总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SmartClaw 扩展点全景图                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 1: Capability Pack (业务场景包)          零代码 YAML  │   │
│  │  capability_packs/{场景名}/manifest.yaml                    │   │
│  │  → 定义场景类型、治理策略、工具约束、输出 Schema              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 2: Step Definition (编排步骤)            零代码 YAML  │   │
│  │  steps/{步骤名}.yaml                                        │   │
│  │  → 定义可复用的编排步骤模板，声明输入/输出/风险/并发          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 3: Skill (技能)                    低代码 MD/YAML/SH  │   │
│  │  skills/{技能名}/SKILL.md 或 skill.yaml                     │   │
│  │  → 定义提示词技能、脚本工具、Python 函数工具                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 4: MCP Server (外部工具)              零代码 YAML     │   │
│  │  config.yaml → mcp.servers.{名称}                           │   │
│  │  → 接入任意 MCP 协议工具服务器，自动桥接为 Agent 工具         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 5: LLM Provider (模型接入)            零代码 YAML     │   │
│  │  config.yaml → providers[]                                  │   │
│  │  → 声明式注册新 LLM Provider，无需修改 ProviderFactory       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 6: Bootstrap 引导文件                   零代码 MD     │   │
│  │  SOUL.md / USER.md / TOOLS.md                               │   │
│  │  → 定义 Agent 人格、用户上下文、工具使用约束                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  扩展点 7: ContextEngine (上下文引擎)         需少量代码      │   │
│  │  ContextEngineRegistry.register("my-engine", MyEngine)      │   │
│  │  → 插件式替换上下文管理策略                                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 扩展点 1：Capability Pack — 业务场景包（核心扩展机制）

Capability Pack 是 SmartClaw 最重要的扩展机制，每个业务场景对应一个 Pack。它定义了"这个场景下 Agent 能做什么、不能做什么、怎么做"。

#### 目录结构

```
# 三级优先级：workspace > global > builtin
~/.smartclaw/workspace/capability_packs/   # workspace 级
~/.smartclaw/capability_packs/             # global 级（跨项目共享）

# 每个 Pack 一个目录
capability_packs/
  ├── security-governance/        # 安全治理场景
  │   ├── manifest.yaml           # 场景定义（必须）
  │   ├── prompt.md               # 可选：外部提示词文件
  │   └── result_schema.json      # 可选：输出 JSON Schema
  ├── devops-inspection/          # 运维巡检场景
  │   └── manifest.yaml
  ├── data-analysis/              # 数据分析场景
  │   └── manifest.yaml
  └── compliance-audit/           # 合规审计场景
      └── manifest.yaml
```

#### manifest.yaml 完整字段说明

```yaml
# === 基本信息 ===
name: devops-inspection              # 唯一标识（kebab-case）
description: 运维巡检与自动化整改      # 场景描述
version: "1.0.0"                     # 版本号

# === 场景路由 ===
scenario_types:                      # 场景类型标签（ModeRouter 用于自动路由）
  - inspection
  - batch_job
preferred_mode: orchestrator         # 首选执行模式：classic | orchestrator
task_profile: multi_stage            # 任务画像：multi_stage | parallelizable | batch

# === 提示词 ===
prompt: |                            # 内联提示词（或用 prompt_file 引用外部文件）
  你是一个运维巡检专家...
# prompt_file: prompt.md            # 外部提示词文件（相对于 manifest.yaml）

# === 步骤约束 ===
allowed_steps:                       # 允许使用的 Step（白名单）
  - inspect
  - remediation_plan
  - remediation_apply
  - report
preferred_steps:                     # 优先使用的 Step（影响 Planner 排序）
  - inspect
  - remediation_plan
  - report

# === 工具约束 ===
allowed_tools:                       # 允许使用的工具（白名单，空=全部允许）
  - shell
  - read_file
  - web_search
denied_tools:                        # 禁止使用的工具（黑名单）
  - write_file                       # 巡检场景禁止写文件
tool_groups:                         # 工具分组（用于并发限制）
  inspection: [shell, read_file]
  network: [web_search, web_fetch]

# === 治理策略 ===
approval_required: true              # 执行前是否需要用户审批
approval_message: 请确认是否允许执行整改操作
concurrency_limits:                  # 按工具组限制并发数
  inspection: 3
  network: 2

# === 输出约束 ===
result_format: json                  # 输出格式：text | json
schema_enforced: true                # 是否强制 JSON Schema 校验
result_schema: |                     # 内联 JSON Schema
  {
    "type": "object",
    "properties": {
      "summary": {"type": "string"},
      "findings": {"type": "array"},
      "risk_level": {"type": "string", "enum": ["low","medium","high"]}
    },
    "required": ["summary", "findings", "risk_level"]
  }
# result_schema_file: result_schema.json  # 或引用外部 Schema 文件
max_schema_retries: 2                # Schema 校验失败后重试次数

# === 容错策略 ===
max_task_retries: 2                  # 单个任务最大重试次数
max_replanning_rounds: 3             # 最大重新规划轮次
repeated_error_threshold: 3          # 重复错误检测阈值（触发 guardrail）
retry_on_error: true                 # 是否在错误时自动重试

# === 自定义元数据 ===
metadata:
  scope: production_servers
  owner: ops-team
  sla_minutes: 30
```

#### 业务场景示例

以下是几个典型业务系统的 Capability Pack 示例：

**示例 1：数据库巡检**
```yaml
name: database-inspection
description: 数据库健康巡检与性能优化建议
scenario_types: [inspection, database]
preferred_mode: orchestrator
task_profile: multi_stage
allowed_steps: [inspect, report]
denied_tools: [write_file, edit_file]    # 只读，不允许修改
result_format: json
schema_enforced: true
approval_required: false
metadata:
  target: mysql,postgresql,redis
```

**示例 2：API 接口测试**
```yaml
name: api-testing
description: REST API 自动化测试与报告生成
scenario_types: [testing, api]
preferred_mode: orchestrator
task_profile: parallelizable
allowed_tools: [shell, web_fetch, web_search, read_file, write_file]
concurrency_limits:
  api_call: 5
max_task_retries: 3
result_format: json
schema_enforced: true
```

**示例 3：合规审计**
```yaml
name: compliance-audit
description: 信息安全合规审计（等保/ISO27001）
scenario_types: [inspection, compliance]
preferred_mode: orchestrator
approval_required: true
approval_message: 合规审计将读取系统配置文件，请确认授权
denied_tools: [shell]                    # 禁止执行命令，只做文件分析
result_format: json
schema_enforced: true
```

### 7.3 扩展点 2：Step Definition — 编排步骤模板

Step 是 Orchestrator 模式下的可复用编排单元。Planner 从 Step Registry 中选择合适的 Step 组成执行计划。

#### 目录结构

```
# 三级优先级：workspace > global > builtin
~/.smartclaw/workspace/steps/          # workspace 级
~/.smartclaw/steps/                    # global 级
smartclaw/steps/builtin/               # 内置（框架自带）

# 每个 Step 一个 YAML 文件
steps/
  ├── inspect.yaml                     # 巡检步骤
  ├── remediation_plan.yaml            # 整改方案步骤
  ├── remediation_apply.yaml           # 整改执行步骤
  ├── report.yaml                      # 报告生成步骤
  ├── db_health_check.yaml             # 自定义：数据库健康检查
  └── api_smoke_test.yaml              # 自定义：API 冒烟测试
```

#### Step YAML 完整字段说明

```yaml
id: db-health-check                    # 唯一标识
domain: database                       # 领域标签
description: 检查数据库连接、慢查询、表空间等健康指标

# === 输入输出 ===
required_inputs: []                    # 必需的用户输入
consumes_artifact_types:               # 消费的上游 Artifact 类型
  - connection_config                  # 依赖连接配置产物
outputs:                               # 产出的 Artifact 类型
  - db_health_result

# === 执行特性 ===
preferred_skill: db-check-skill        # 首选技能（SkillsRegistry 中的名称）
can_parallel: true                     # 是否支持并行执行
risk_level: low                        # 风险等级：low | medium | high | critical
side_effect_level: read_only           # 副作用等级：read_only | write | destructive
kind: inspection                       # 步骤类型：inspection | remediation | report | generic
completion_signal: db_health_ready     # 完成信号标识

# === 编排控制 ===
plan_role: core                        # 规划角色：core | conditional | terminal
activation_mode: immediate             # 激活模式：immediate | after_artifact
display_policy: always_show            # 展示策略：always_show | on_demand
intent_tags:                           # 意图标签（Planner 匹配用）
  - database
  - health_check
  - monitoring
default_depends_on:                    # 默认依赖的前置步骤
  - connection_setup
```

#### Step 之间的 Artifact 流转

```
Step A (inspect)          Step B (remediation_plan)       Step C (report)
  │                           │                               │
  │ outputs:                  │ consumes:                     │ consumes:
  │   - inspection_result     │   - inspection_result         │   - inspection_result
  │                           │ outputs:                      │   - remediation_plan_result
  └──── Artifact ────────────▶│   - remediation_plan_result   │
                              └──── Artifact ────────────────▶│ outputs:
                                                              │   - report_result
```

Planner 根据 `consumes_artifact_types` 和 `outputs` 自动推导步骤依赖关系，无需手动编排 DAG。

### 7.4 扩展点 3：Skill — 技能扩展

Skill 是 Agent 的"能力单元"，支持三种格式，覆盖从纯提示词到脚本执行的全部场景。

#### 目录结构

```
# 三级优先级：workspace > global > builtin
~/.smartclaw/workspace/skills/         # workspace 级（最高优先级）
~/.smartclaw/skills/                   # global 级（跨项目共享）
smartclaw/skills/builtin/              # 内置

# 每个 Skill 一个目录
skills/
  ├── db-check-skill/                  # 数据库检查技能
  │   ├── SKILL.md                     # 技能定义
  │   └── scripts/                     # 自动发现的脚本
  │       ├── check_mysql.sh
  │       ├── check_redis.py
  │       └── check_postgres.sh
  ├── k8s-ops/                         # K8s 运维技能
  │   ├── skill.yaml                   # YAML 格式定义
  │   └── scripts/
  │       └── kubectl_wrapper.sh
  └── code-review/                     # 代码审查技能（纯提示词）
      └── SKILL.md
```

#### 格式 1：SKILL.md（Markdown 提示词技能 + 可选脚本工具）

```markdown
---
name: db-check-skill
description: 数据库健康检查技能，支持 MySQL/PostgreSQL/Redis
tools:
  - name: check_mysql
    description: 检查 MySQL 数据库健康状态
    type: shell
    command: "bash"
    args: ["{skill_dir}/scripts/check_mysql.sh", "{host}", "{port}"]
    timeout: 30
    parameters:
      host:
        type: string
        description: 数据库主机地址
      port:
        type: string
        description: 数据库端口
        default: "3306"
  - name: check_redis
    description: 检查 Redis 健康状态
    type: exec
    command: "python3"
    args: ["{skill_dir}/scripts/check_redis.py"]
    timeout: 15
---

# Database Health Check Skill

你是一个数据库运维专家。当用户要求检查数据库健康状态时：

1. 使用 check_mysql / check_redis 工具获取数据库状态
2. 分析慢查询、连接数、内存使用等关键指标
3. 给出优化建议

## 注意事项
- 只执行只读操作，不要修改任何数据库配置
- 敏感信息（密码、连接串）不要出现在输出中
```

#### 格式 2：skill.yaml（Python 函数工具）

```yaml
name: k8s-ops
description: Kubernetes 运维操作技能
entry_point: "k8s_ops.tools:register_tools"
version: "1.0.0"
tools:
  - name: kubectl_get
    description: 获取 K8s 资源状态
    type: shell
    command: "bash"
    args: ["{skill_dir}/scripts/kubectl_wrapper.sh", "get", "{resource}"]
    timeout: 30
    deny_patterns:
      - "delete"
      - "drain"
    parameters:
      resource:
        type: string
        description: K8s 资源类型（pods/services/deployments 等）
```

#### 格式 3：纯提示词技能（无工具）

```markdown
---
name: code-review
description: 代码审查技能，提供代码质量分析和改进建议
---

# Code Review Skill

你是一个资深代码审查专家。审查代码时关注以下方面：

1. **安全性**：SQL 注入、XSS、敏感信息泄露
2. **性能**：N+1 查询、内存泄漏、不必要的循环
3. **可维护性**：命名规范、函数长度、圈复杂度
4. **最佳实践**：错误处理、日志记录、单元测试覆盖

输出格式：按严重程度（Critical > Major > Minor）排列发现的问题。
```

#### scripts/ 自动发现机制

`SKILL.md` 所在目录下的 `scripts/` 子目录中的可执行文件会被自动发现并注册为 Native Command 工具：
- `.sh` → type: shell
- `.py` → type: exec (python3)
- 其他可执行文件 → type: exec

无需在 SKILL.md 的 frontmatter 中显式声明，放进 `scripts/` 即可使用。

### 7.5 扩展点 4：MCP Server — 外部工具接入

通过 MCP 协议接入外部工具服务器，Agent 自动发现并使用这些工具，无需编写任何适配代码。

#### 配置方式

在 `config/config.yaml` 中添加：

```yaml
mcp:
  enabled: true
  servers:
    # 示例 1：接入数据库查询 MCP Server（stdio 传输）
    db-query:
      enabled: true
      command: "uvx"
      args: ["db-query-mcp-server@latest"]
      env:
        DB_HOST: "localhost"
        DB_PORT: "3306"
        DB_USER: "readonly"
      env_file: ".env.db"             # 也可以从 env_file 加载敏感变量

    # 示例 2：接入 JIRA MCP Server（HTTP 传输）
    jira:
      enabled: true
      type: http
      url: "https://jira-mcp.internal.company.com/mcp"
      headers:
        Authorization: "Bearer ${JIRA_TOKEN}"

    # 示例 3：接入 Kubernetes MCP Server
    k8s:
      enabled: true
      command: "python3"
      args: ["-m", "k8s_mcp_server"]
      env:
        KUBECONFIG: "~/.kube/config"

    # 示例 4：接入 Prometheus 监控 MCP Server
    prometheus:
      enabled: true
      type: http
      url: "http://prometheus-mcp:8080/mcp"

    # 示例 5：接入自研业务系统 MCP Server
    biz-system:
      enabled: true
      command: "node"
      args: ["./mcp-servers/biz-system/index.js"]
      env:
        API_BASE: "https://api.internal.company.com"
        API_TOKEN: "${BIZ_API_TOKEN}"
```

#### MCP 工具自动桥接流程

```
MCP Server 启动
      │
      ▼
MCPManager.initialize()
      │
      ▼
session.list_tools()          ← 自动发现 MCP Server 暴露的所有工具
      │
      ▼
MCPTool(BaseTool) 桥接        ← 每个 MCP 工具自动包装为 LangChain BaseTool
      │
      ▼
ToolRegistry.register()       ← 注册到统一工具注册中心
      │
      ▼
Agent 可直接调用              ← LLM 在推理时自动选择和调用这些工具
```

### 7.6 扩展点 5：LLM Provider — 模型接入

通过 `config.yaml` 声明式注册新的 LLM Provider，无需修改 `ProviderFactory` 源码。

```yaml
providers:
  # 接入 DeepSeek
  - name: deepseek
    class_path: "langchain_openai.ChatOpenAI"
    env_key: "DEEPSEEK_API_KEY"
    base_url: "https://api.deepseek.com/v1"
    model_field: "model"
    supports_vision: false
    extra_params:
      timeout: 60

  # 接入本地 Ollama
  - name: ollama
    class_path: "langchain_openai.ChatOpenAI"
    env_key: "OLLAMA_API_KEY"
    base_url: "http://localhost:11434/v1"
    supports_vision: false

  # 接入通义千问
  - name: qwen
    class_path: "langchain_openai.ChatOpenAI"
    env_key: "QWEN_API_KEY"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    supports_vision: true
    model_capabilities:
      qwen-vl-max:
        supports_vision: true
      qwen-turbo:
        supports_vision: false

  # 接入 Azure OpenAI
  - name: azure
    class_path: "langchain_openai.AzureChatOpenAI"
    env_key: "AZURE_OPENAI_API_KEY"
    extra_params:
      azure_endpoint: "https://my-resource.openai.azure.com"
      api_version: "2024-02-01"

# 注册后即可在 model 配置中使用
model:
  primary: "deepseek/deepseek-chat"
  fallbacks:
    - "qwen/qwen-turbo"
    - "ollama/llama3"
    - "kimi/kimi-k2.5"
```

#### AuthProfile 多 Key 轮转

同一 Provider 配置多个 API Key，Fallback Chain 会在 Key 级别轮转：

```yaml
model:
  primary: "kimi/kimi-k2.5"
  auth_profiles:
    - profile_id: "kimi-prod-1"
      provider: "kimi"
      env_key: "KIMI_API_KEY_1"
    - profile_id: "kimi-prod-2"
      provider: "kimi"
      env_key: "KIMI_API_KEY_2"
    - profile_id: "kimi-backup"
      provider: "kimi"
      env_key: "KIMI_API_KEY_BACKUP"
      base_url: "https://api-backup.moonshot.cn/v1"
  session_sticky: true                # 优先使用上次成功的 Key
```

### 7.7 扩展点 6：Bootstrap 引导文件 — Agent 行为定制

通过 Markdown 文件定制 Agent 的人格、上下文和工具使用规范，无需修改代码。

#### 文件说明

| 文件 | 用途 | 示例 |
|------|------|------|
| `SOUL.md` | Agent 人格与行为准则 | "你是一个严谨的运维工程师，所有操作前必须确认..." |
| `USER.md` | 用户/团队上下文 | "我们使用 K8s + MySQL + Redis 技术栈，生产环境在 AWS..." |
| `TOOLS.md` | 工具使用约束与指南 | "使用 shell 工具时禁止执行 rm -rf，web_fetch 超时设为 10s..." |

#### 目录优先级

```
workspace/.smartclaw/SOUL.md     ← 最高优先级（项目级）
~/.smartclaw/SOUL.md             ← 全局级（用户级）
```

#### 示例：运维场景的 SOUL.md

```markdown
# SmartClaw 运维助手

你是一个资深运维工程师，遵循以下原则：

## 安全第一
- 所有写操作前必须确认
- 禁止在生产环境执行 DROP/DELETE/TRUNCATE
- 敏感信息（密码、Token）不得出现在输出中

## 操作规范
- 每次操作前先检查当前环境（dev/staging/prod）
- 变更操作必须有回滚方案
- 所有操作记录完整的执行日志

## 输出规范
- 使用结构化格式输出巡检结果
- 风险项按严重程度排序
- 给出具体的修复命令和步骤
```

### 7.8 扩展点 7：ContextEngine — 上下文引擎插件

当内置的 `LegacyContextEngine` 不满足需求时，可以注册自定义的上下文管理引擎。

#### 注册方式

```python
from smartclaw.context_engine.interface import ContextEngine
from smartclaw.context_engine.registry import ContextEngineRegistry

class RAGContextEngine(ContextEngine):
    """基于 RAG 的上下文引擎，从向量数据库检索相关上下文。"""

    async def bootstrap(self, session_key, system_prompt=None):
        # 初始化向量索引连接
        ...

    async def assemble(self, messages, system_prompt=None):
        # 从向量库检索相关文档，注入到消息列表
        ...

    async def compact(self, session_key, messages, force=False):
        # 自定义压缩策略
        ...

    # ... 实现其他抽象方法

# 注册
ContextEngineRegistry.register("rag", RAGContextEngine)
```

#### 配置启用

```yaml
# config.yaml
context_engine: "rag"    # 使用自定义的 RAG 引擎替代默认的 legacy 引擎
```

---

## 8. 多业务系统扩展实战：端到端示例

以下演示如何为一个完整的业务场景（"电商系统全链路巡检"）进行零代码扩展。

### 8.1 场景描述

电商系统包含：MySQL 数据库、Redis 缓存、Nginx 网关、Spring Boot 应用、K8s 集群。需要定期巡检并生成报告。

### 8.2 扩展步骤

#### Step 1：创建 Capability Pack

```bash
mkdir -p ~/.smartclaw/capability_packs/ecommerce-inspection
```

```yaml
# ~/.smartclaw/capability_packs/ecommerce-inspection/manifest.yaml
name: ecommerce-inspection
description: 电商系统全链路巡检（DB + Cache + Gateway + App + K8s）
version: "1.0.0"

scenario_types:
  - inspection
  - ecommerce
  - full_stack

preferred_mode: orchestrator
task_profile: multi_stage

allowed_steps:
  - db-health-check
  - redis-health-check
  - nginx-check
  - app-health-check
  - k8s-cluster-check
  - report

preferred_steps:
  - db-health-check
  - redis-health-check
  - nginx-check
  - app-health-check
  - k8s-cluster-check
  - report

denied_tools:
  - write_file
  - edit_file
  - append_file

approval_required: false
result_format: json
schema_enforced: true
result_schema_file: result_schema.json

concurrency_limits:
  inspection: 3
  report: 1

max_task_retries: 2
max_replanning_rounds: 2

metadata:
  scope: production
  owner: sre-team
  schedule: daily
```

#### Step 2：定义 Step 模板

```yaml
# ~/.smartclaw/steps/db-health-check.yaml
id: db-health-check
domain: database
description: 检查 MySQL 数据库连接数、慢查询、表空间、主从延迟
required_inputs: []
consumes_artifact_types: []
outputs:
  - db_health_result
preferred_skill: db-check-skill
can_parallel: true
risk_level: low
side_effect_level: read_only
kind: inspection
plan_role: core
activation_mode: immediate
intent_tags: [database, mysql, health_check]
```

```yaml
# ~/.smartclaw/steps/redis-health-check.yaml
id: redis-health-check
domain: cache
description: 检查 Redis 内存使用、连接数、命中率、持久化状态
required_inputs: []
consumes_artifact_types: []
outputs:
  - redis_health_result
preferred_skill: redis-check-skill
can_parallel: true
risk_level: low
side_effect_level: read_only
kind: inspection
plan_role: core
activation_mode: immediate
intent_tags: [redis, cache, health_check]
```

#### Step 3：创建 Skill 技能

```bash
mkdir -p ~/.smartclaw/skills/db-check-skill/scripts
```

```markdown
# ~/.smartclaw/skills/db-check-skill/SKILL.md
---
name: db-check-skill
description: MySQL 数据库健康检查技能
tools:
  - name: mysql_health
    description: 执行 MySQL 健康检查脚本
    type: shell
    command: "bash"
    args: ["{skill_dir}/scripts/check_mysql.sh"]
    timeout: 30
---

# MySQL Health Check

检查 MySQL 数据库的以下指标：
- 连接数（当前/最大）
- 慢查询数量（最近 1 小时）
- 表空间使用率
- 主从复制延迟
- InnoDB Buffer Pool 命中率
```

```bash
# ~/.smartclaw/skills/db-check-skill/scripts/check_mysql.sh
#!/bin/bash
echo "=== MySQL Health Check ==="
mysql -h ${DB_HOST:-localhost} -u ${DB_USER:-root} -e "
  SHOW STATUS LIKE 'Threads_connected';
  SHOW STATUS LIKE 'Slow_queries';
  SHOW STATUS LIKE 'Innodb_buffer_pool_read_requests';
  SHOW STATUS LIKE 'Innodb_buffer_pool_reads';
  SHOW SLAVE STATUS\G
" 2>/dev/null || echo "MySQL connection failed"
```

#### Step 4：接入 MCP Server（可选）

```yaml
# config/config.yaml 追加
mcp:
  enabled: true
  servers:
    prometheus:
      enabled: true
      type: http
      url: "http://prometheus-mcp:8080/mcp"
    grafana:
      enabled: true
      command: "uvx"
      args: ["grafana-mcp-server@latest"]
      env:
        GRAFANA_URL: "http://grafana:3000"
        GRAFANA_TOKEN: "${GRAFANA_TOKEN}"
```

#### Step 5：定制 Bootstrap 文件

```markdown
# ~/.smartclaw/SOUL.md
# 电商系统 SRE 助手

你是电商系统的 SRE 运维专家，负责全链路巡检。

## 巡检原则
- 所有操作只读，不修改任何配置
- 按 DB → Cache → Gateway → App → K8s 顺序巡检
- 发现问题按 P0/P1/P2 分级

## 输出要求
- 每个组件输出健康评分（0-100）
- 异常项给出具体指标值和阈值对比
- 最终生成 JSON 格式的巡检报告
```

### 8.3 最终效果

完成以上 5 步后，无需修改任何 SmartClaw 源码，用户只需输入：

```
> 对电商系统进行全链路巡检
```

SmartClaw 会自动：
1. `ModeRouter` 识别关键词"巡检"，路由到 `orchestrator` 模式
2. 匹配 `ecommerce-inspection` Capability Pack
3. `Planner` 从 Step Registry 选择 5 个巡检步骤 + 1 个报告步骤
4. `Dispatcher` 并发执行 db/redis/nginx/app/k8s 巡检（受 `concurrency_limits: 3` 约束）
5. 各步骤调用对应 Skill 中的脚本工具
6. `report` 步骤消费所有巡检 Artifact，生成结构化报告
7. 输出经过 JSON Schema 校验的巡检报告

```
Orchestrator 执行流程：

Phase 1 (并发, max=3):
  ├── db-health-check     → db_health_result
  ├── redis-health-check  → redis_health_result
  └── nginx-check         → nginx_health_result

Phase 2 (并发, max=3):
  ├── app-health-check    → app_health_result
  └── k8s-cluster-check   → k8s_health_result

Phase 3 (串行):
  └── report              → 消费所有 *_result → 最终巡检报告 (JSON)
```

---

## 9. 扩展决策树：我该用哪个扩展点？

```
我有一个新的业务场景需要接入 SmartClaw
  │
  ├─ 需要定义"这个场景下 Agent 能做什么"？
  │   └─ → Capability Pack (manifest.yaml)
  │
  ├─ 需要定义"执行分几步、每步做什么"？
  │   └─ → Step Definition (steps/*.yaml)
  │
  ├─ 需要给 Agent 增加新的"能力/工具"？
  │   │
  │   ├─ 能力是一段提示词/知识？
  │   │   └─ → SKILL.md（纯提示词技能）
  │   │
  │   ├─ 能力是执行一个脚本/命令？
  │   │   └─ → SKILL.md + scripts/（Native Command 技能）
  │   │
  │   ├─ 能力是调用一个外部 API/服务？
  │   │   └─ → MCP Server（config.yaml 配置）
  │   │
  │   └─ 能力是一个复杂的 Python 函数？
  │       └─ → skill.yaml + entry_point（Python 函数技能）
  │
  ├─ 需要接入新的 LLM 模型？
  │   └─ → providers[] (config.yaml 配置)
  │
  ├─ 需要定制 Agent 的行为风格/约束？
  │   └─ → SOUL.md / USER.md / TOOLS.md
  │
  └─ 需要自定义上下文管理策略？
      └─ → ContextEngine 插件（少量 Python 代码）
```

---

## 10. 扩展机制对比表

| 扩展点 | 修改代码 | 格式 | 热重载 | 适用场景 |
|--------|---------|------|--------|---------|
| Capability Pack | ❌ 零代码 | YAML | ✅ | 定义业务场景的治理策略、工具约束、输出规范 |
| Step Definition | ❌ 零代码 | YAML | ✅ | 定义可复用的编排步骤模板 |
| Skill (SKILL.md) | ❌ 零代码 | Markdown + YAML frontmatter | ✅ | 提示词技能 + 脚本工具 |
| Skill (skill.yaml) | 🔸 少量代码 | YAML + Python | ✅ | Python 函数工具 |
| MCP Server | ❌ 零代码 | YAML 配置 | 需重启 | 接入外部工具服务 |
| LLM Provider | ❌ 零代码 | YAML 配置 | 需重启 | 接入新的 LLM 模型 |
| Bootstrap 文件 | ❌ 零代码 | Markdown | ✅ | 定制 Agent 人格与行为约束 |
| ContextEngine | 🔸 少量代码 | Python 类 | 需重启 | 自定义上下文管理策略 |

---

## 11. 多业务系统并行管理建议

当你有多个业务系统需要接入时，推荐以下目录组织方式：

```
~/.smartclaw/
  ├── capability_packs/              # 全局 Capability Pack
  │   ├── security-governance/       # 通用安全治理
  │   ├── ecommerce-inspection/      # 电商系统巡检
  │   ├── payment-audit/             # 支付系统审计
  │   ├── crm-data-analysis/         # CRM 数据分析
  │   └── devops-automation/         # DevOps 自动化
  │
  ├── steps/                         # 全局 Step 定义
  │   ├── db-health-check.yaml       # 通用数据库检查
  │   ├── redis-health-check.yaml    # 通用 Redis 检查
  │   ├── api-smoke-test.yaml        # 通用 API 冒烟测试
  │   ├── log-analysis.yaml          # 通用日志分析
  │   └── report.yaml                # 通用报告生成
  │
  ├── skills/                        # 全局 Skill
  │   ├── db-check-skill/            # 数据库检查技能
  │   ├── redis-check-skill/         # Redis 检查技能
  │   ├── k8s-ops/                   # K8s 运维技能
  │   ├── log-parser/                # 日志解析技能
  │   └── report-generator/          # 报告生成技能
  │
  ├── SOUL.md                        # 全局 Agent 人格
  ├── USER.md                        # 全局用户上下文
  └── TOOLS.md                       # 全局工具约束

# 各项目 workspace 可覆盖全局配置
project-a/.smartclaw/
  ├── capability_packs/              # 项目级 Pack（覆盖全局同名 Pack）
  ├── steps/                         # 项目级 Step
  ├── skills/                        # 项目级 Skill
  └── SOUL.md                        # 项目级 Agent 人格
```

#### 核心原则

1. **通用能力放 global**：数据库检查、日志分析、报告生成等跨项目复用的 Step 和 Skill 放在 `~/.smartclaw/` 下
2. **业务特化放 workspace**：特定项目的 Capability Pack、定制化 Step 放在项目的 `.smartclaw/` 下
3. **workspace 覆盖 global**：同名资源 workspace 级优先，实现项目级定制
4. **Pack 组合 Step + Skill**：Capability Pack 通过 `allowed_steps` 和 `preferred_steps` 组合已有的 Step，Step 通过 `preferred_skill` 关联 Skill，形成 Pack → Step → Skill 的三层组合
5. **MCP 接入外部系统**：业务系统的 API 通过 MCP Server 接入，Agent 自动发现和调用

```
扩展组合关系：

Capability Pack ──(allowed_steps)──▶ Step Definition
                                        │
                                  (preferred_skill)
                                        │
                                        ▼
                                      Skill ──(tools)──▶ scripts/ | MCP | Python
```
