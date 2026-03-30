# 企业级多 Agent 框架 — 模块选型方案

> 基础底座：DeerFlow 2.0（字节跳动）
> 设计原则：代码只做引擎，配置驱动业务扩展
> 决策依据：SmartClaw / OpenClaw / CrewAI / LangGraph 对比调研

---

## 设计原则

1. **DeerFlow 为底座** — 保留其 LangGraph + FastAPI + Next.js 技术栈和 Harness/App 分层架构
2. **砍掉不需要的** — 去掉与企业通用场景无关的内置 Skills 和工具
3. **补齐短板** — 从 SmartClaw/OpenClaw 等框架借鉴 DeerFlow 缺失的关键能力
4. **配置驱动** — 所有业务差异通过配置 + Skill + MCP 表达，不改框架代码

---

## 总览：8 层模块选型决策

| 层 | 决策 | 说明 |
|----|------|------|
| 1. LLM 模型层 | DeerFlow 为主 + 借鉴 SmartClaw Fallback | DeerFlow 模型工厂好用，但需补 Fallback Chain |
| 2. Agent 编排层 | DeerFlow 为主 + 借鉴 SmartClaw Orchestrator | DeerFlow Lead Agent + SubAgent 保留，补动态编排 |
| 3. 工具与能力层 | DeerFlow 为主 + 精简 Skills + 补浏览器工具 | 砍掉内置 Skills，保留框架机制 |
| 4. 上下文与记忆层 | DeerFlow 为主 + 借鉴 SmartClaw 多级压缩 + 补 RAG | DeerFlow 记忆好，压缩需加强 |
| 5. 安全与治理层 | DeerFlow 为主 + 借鉴 SmartClaw 治理体系 | DeerFlow 沙箱+Guardrail 保留，补场景级治理 |
| 6. 可观测与可审计层 | 借鉴 SmartClaw 为主 | DeerFlow 几乎空白，需从 SmartClaw 移植 |
| 7. API 与接入层 | DeerFlow 为主 | DeerFlow Gateway+UI 保留，砍掉 IM 渠道 |
| 8. 部署与运维层 | DeerFlow 为主 + 补成本管控 | DeerFlow Docker 方案保留 |

---

## 逐层详细选型


### 第 1 层：LLM 模型层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| 模型工厂（Model Factory） | ✅ 保留 DeerFlow | DeerFlow `create_chat_model()` | 配置驱动 `use: class_path`，支持 thinking/vision 标记，反射加载，够用 |
| 多 Provider 配置 | ✅ 保留 DeerFlow | DeerFlow `config.yaml → models[]` | YAML 声明式注册，支持 OpenRouter/Codex/Claude Code，灵活度够 |
| Thinking/推理模式 | ✅ 保留 DeerFlow | DeerFlow `supports_thinking` + `when_thinking_enabled` | DeerFlow 原生支持，SmartClaw 没有 |
| Vision/多模态 | ✅ 保留 DeerFlow | DeerFlow `supports_vision` + `ViewImageMiddleware` | 完整的视觉链路（标记→中间件→工具），比 SmartClaw 更完善 |
| **Fallback Chain** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `FallbackChain` | DeerFlow 最大短板。需实现：primary→fallbacks 列表、错误分类、指数退避 Cooldown、AuthProfile 多 Key 轮转 |
| 运行时模型切换 | ✅ 保留 DeerFlow | DeerFlow `configurable.model_name` | 前端选择 + 运行时配置，够用 |

**砍掉的：**
- DeerFlow 的 `CodexChatModel` 和 `ClaudeChatModel` CLI Provider — 这两个是通过 CLI 工具调用模型的特殊 Provider，企业场景用不到，统一走 API 即可

**需要开发的核心工作：**
- Fallback Chain 引擎（参考 SmartClaw 的 `FallbackChain` + `CooldownTracker` + `classify_error()`）


---

### 第 2 层：Agent 编排层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| Lead Agent 主代理 | ✅ 保留 DeerFlow | DeerFlow `make_lead_agent()` | LangGraph StateGraph 驱动，动态工具加载，系统提示词组装，成熟稳定 |
| Middleware 链 | ✅ 保留 DeerFlow（精简） | DeerFlow 12 个 Middleware | 保留核心 Middleware，砍掉不需要的（见下方） |
| SubAgent 子代理 | ✅ 保留 DeerFlow | DeerFlow `SubagentExecutor` | 并发 3 个 + 15 分钟超时 + SSE 事件 + 双线程池，实现完善 |
| Plan Mode | ✅ 保留 DeerFlow | DeerFlow `TodoListMiddleware` | 任务清单模式，适合多步骤任务 |
| **Orchestrator 动态编排** | 🟡 后续借鉴 SmartClaw | SmartClaw Orchestrator | DeerFlow 的 Plan Mode 是"任务清单"，SmartClaw 的 Orchestrator 是真正的"动态编排"（Plan→Dispatch→Execute→Review→Synthesize）。P2 阶段再补 |
| **循环检测** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `LoopDetector` | DeerFlow 只有递归限制，没有语义级循环检测。需实现 hash 滑动窗口 + 三级状态 |
| **自动模式路由** | 🟡 后续借鉴 SmartClaw | SmartClaw `ModeRouter` | 根据任务特征自动选择 Classic/Orchestrator 模式。等 Orchestrator 补齐后再加 |
| Flash/Standard/Pro/Ultra 模式 | 🔴 砍掉 | DeerFlow 前端概念 | 这是 DeerFlow 前端的 UI 概念，不是编排层能力。企业框架通过配置决定执行模式 |

**Middleware 精简方案：**

| # | Middleware | 决策 | 理由 |
|---|-----------|------|------|
| 1 | ThreadDataMiddleware | ✅ 保留 | 每线程隔离目录，核心基础设施 |
| 2 | UploadsMiddleware | ✅ 保留 | 文件上传注入，企业场景需要 |
| 3 | SandboxMiddleware | ✅ 保留 | 沙箱获取，安全执行的基础 |
| 4 | DanglingToolCallMiddleware | ✅ 保留 | 修复中断导致的悬挂工具调用，健壮性保障 |
| 5 | GuardrailMiddleware | ✅ 保留 | 工具级授权，安全核心 |
| 6 | SummarizationMiddleware | ✅ 保留（需增强） | 上下文压缩，但需要从单级增强到多级 |
| 7 | TodoListMiddleware | ✅ 保留 | Plan Mode 任务追踪 |
| 8 | TitleMiddleware | ✅ 保留 | 自动生成会话标题，用户体验 |
| 9 | MemoryMiddleware | ✅ 保留 | 记忆提取队列，核心能力 |
| 10 | ViewImageMiddleware | ✅ 保留 | 视觉模型支持 |
| 11 | SubagentLimitMiddleware | ✅ 保留 | 子代理并发限制 |
| 12 | ClarificationMiddleware | ✅ 保留 | 交互式澄清，HITL 基础 |

结论：12 个 Middleware 全部保留，不砍。DeerFlow 的 Middleware 设计每个都有明确职责，没有冗余。


---

### 第 3 层：工具与能力层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| 沙箱工具（bash/ls/read/write/str_replace） | ✅ 保留 DeerFlow | DeerFlow `sandbox/tools.py` | 核心文件操作和命令执行，沙箱内安全运行 |
| 内置工具（present_files/ask_clarification/view_image/task） | ✅ 保留 DeerFlow | DeerFlow `tools/builtins/` | 每个都有明确用途，不砍 |
| MCP 协议支持 | ✅ 保留 DeerFlow | DeerFlow `mcp/` | stdio + SSE + HTTP + OAuth + 懒加载 + mtime 缓存，实现完善 |
| Skills 技能系统 | ✅ 保留 DeerFlow 框架机制 | DeerFlow `skills/` | SKILL.md + 渐进式加载 + .skill 安装 + public/custom 分离，机制很好 |
| 工具注册/组装 | ✅ 保留 DeerFlow | DeerFlow `get_available_tools()` | 动态组装沙箱+内置+MCP+社区+子代理工具 |

**内置 Skills 精简方案（重点砍的地方）：**

| Skill | 决策 | 理由 |
|-------|------|------|
| research/SKILL.md | 🔴 砍掉 | 深度研究是 DeerFlow v1 的核心场景，企业框架不需要内置，用户按需创建 |
| report-generation/SKILL.md | 🔴 砍掉 | 报告生成是特定业务，不应内置 |
| slide-creation/SKILL.md | 🔴 砍掉 | PPT 生成是特定业务 |
| web-page/SKILL.md | 🔴 砍掉 | 网页生成是特定业务 |
| image-generation/SKILL.md | 🔴 砍掉 | 图片生成是特定业务 |
| claude-to-deerflow/SKILL.md | 🔴 砍掉 | Claude Code 集成，与企业框架无关 |

**结论：砍掉所有内置 Skills，只保留 Skills 框架机制（加载/解析/注入/安装）。** 企业用户通过 `skills/custom/` 目录或 `.skill` 安装包添加自己的业务 Skills。

**社区工具精简方案：**

| 工具 | 决策 | 理由 |
|------|------|------|
| Tavily（Web 搜索） | ✅ 保留 | 通用能力，Agent 需要搜索 |
| Jina AI（Web 抓取） | ✅ 保留 | 通用能力，Agent 需要读网页 |
| Firecrawl（Web 爬取） | 🟡 可选 | 与 Jina AI 功能重叠，保留一个即可 |
| DuckDuckGo（图片搜索） | 🔴 砍掉 | 图片搜索不是企业通用需求 |


---

### 第 4 层：上下文与记忆层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| 记忆系统（Memory） | ✅ 保留 DeerFlow | DeerFlow `agents/memory/` | LLM 驱动提取 + 结构化存储(context/history/facts) + 置信度 + 去重 + 防抖队列，实现优秀 |
| 上下文摘要 | ✅ 保留 DeerFlow（需增强） | DeerFlow `SummarizationMiddleware` | 保留现有单级摘要，后续增强为多级 |
| **多级上下文压缩** | 🔴 需新增，借鉴 SmartClaw | SmartClaw L1-L4 四级压缩 | DeerFlow 只有"接近 token 限制时摘要"一种策略。需要补：L1 工具结果即时截断（ToolResultGuard）、L2 会话级修剪（SessionPruner）、L3 保留现有摘要、L4 超长上下文分块合并 |
| **RAG/知识库** | 🔴 需新增，自研 | 参考 SmartClaw ContextEngine 接口 | 实现一个基于向量数据库的 ContextEngine 插件，支持文档向量化→语义检索→上下文注入 |
| **Bootstrap 引导系统** | 🔴 需新增，借鉴 SmartClaw + OpenClaw | SmartClaw SOUL/USER/TOOLS.md + OpenClaw SOUL.md | DeerFlow 的系统提示词是代码生成的，不够灵活。需要改为 Markdown 文件驱动：SOUL.md（人格）+ USER.md（用户上下文）+ TOOLS.md（工具约束），三级目录优先级（workspace > global） |
| Skills 注入到提示词 | ✅ 保留 DeerFlow | DeerFlow `apply_prompt_template()` | 渐进式加载 + 容器路径注入，设计合理 |
| Memory 注入到提示词 | ✅ 保留 DeerFlow | DeerFlow top 15 facts + context → `<memory>` 标签 | 实现完善 |

**需要开发的核心工作：**
- ToolResultGuard（L1）：工具返回结果即时截断，参考 SmartClaw 的 head+tail 保留策略
- SessionPruner（L2）：会话级 ToolMessage 修剪，双阈值（soft-trim/hard-clear）
- RAG ContextEngine：基于 ChromaDB 或 Qdrant 的向量检索引擎
- Bootstrap 文件加载器：从 SOUL.md/USER.md/TOOLS.md 组装系统提示词


---

### 第 5 层：安全与治理层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| 沙箱隔离（Docker/K8s） | ✅ 保留 DeerFlow | DeerFlow `sandbox/` | Docker 容器 + K8s Pod + 虚拟路径 + 每线程隔离，这是 DeerFlow 最强的模块之一 |
| Guardrail 工具级授权 | ✅ 保留 DeerFlow | DeerFlow `guardrails/` | 3 种 Provider（Allowlist/OAP/Custom）+ fail-closed，实现完善 |
| HITL 交互式澄清 | ✅ 保留 DeerFlow | DeerFlow `ClarificationMiddleware` + `ask_clarification` 工具 | 中断执行流 + 等待用户输入，机制完整 |
| **Capability Pack 场景级治理** | 🔴 需新增，借鉴 SmartClaw | SmartClaw Capability Pack | DeerFlow 的 Guardrail 是工具级的（每次调用评估），缺少场景级的治理（定义"这个业务场景能做什么"）。需要实现：YAML 定义场景包（工具白/黑名单、审批、输出 Schema、重试策略） |
| **路径安全策略** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `PathPolicy` | DeerFlow 靠沙箱虚拟路径做隔离，但缺少显式的路径白/黑名单策略。在沙箱之上再加一层路径策略更安全 |
| **敏感数据脱敏** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `redact_attributes()` | API Key/Email/Secret 模式检测 + 日志/追踪属性自动脱敏。DeerFlow 完全没有 |

**两层治理的关系：**

```
用户请求 → Capability Pack（场景级：这个场景允许用哪些工具？需要审批吗？）
                ↓
         Agent 推理 → 决定调用工具
                ↓
         Guardrail（调用级：这次具体的工具调用参数安全吗？）
                ↓
         沙箱执行（环境级：在隔离容器中执行）
                ↓
         PathPolicy（路径级：访问的文件路径合法吗？）
```

四层安全，从粗到细，层层过滤。


---

### 第 6 层：可观测与可审计层

这是 DeerFlow 最薄弱的层，需要大量借鉴 SmartClaw。

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| **OpenTelemetry 分布式追踪** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `OTELTracingService` | 自动创建 agent.invoke → llm.call → tool.execute.{name} 层级 Span，OTLP gRPC/HTTP 导出。DeerFlow 完全没有 |
| **诊断事件总线** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `DiagnosticBus` | 事件驱动的诊断总线，支持 tool.executed / llm.called / agent.run / session 等事件类型。可以在 DeerFlow 的 Middleware 链中埋点发布事件 |
| **Decision Record 审计** | 🔴 需新增，借鉴 SmartClaw | SmartClaw `DecisionRecord` + `DecisionCollector` | 每步 LLM 决策记录为不可变记录（时间戳、迭代轮次、决策类型、推理过程、工具调用）。按 session 分组存储 |
| **结构化日志** | 🔴 需新增，借鉴 SmartClaw | SmartClaw structlog | 替换 DeerFlow 的 Python logging 为 structlog，支持 console/JSON 双格式 + 组件级标签 |
| **成本追踪** | 🔴 需新增，自研 | 参考行业实践 | 每次 LLM 调用记录 token 消耗和成本，按 Agent/任务/用户/会话维度聚合 |
| **Debug UI（SSE 事件流）** | 🟡 后续新增，借鉴 SmartClaw | SmartClaw SSE Debug Stream | hook-events / decision-events / execution-events 三个 SSE 端点，实时推送到调试界面 |

**实现策略：**

不需要一次性全部实现。建议分阶段：
- P0：结构化日志（structlog 替换 logging，工作量小，收益大）
- P1：OTEL 追踪（在 Middleware 链中埋点，agent/llm/tool 三级 Span）
- P1：成本追踪（在 LLM 调用后记录 token 消耗）
- P2：Decision Record（在 LLM 响应后记录决策）
- P2：诊断事件总线 + Debug UI


---

### 第 7 层：API 与接入层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| Gateway API（FastAPI） | ✅ 保留 DeerFlow | DeerFlow `app/gateway/` | models/mcp/skills/memory/uploads/threads/artifacts/suggestions 完整 REST API |
| LangGraph Server | ✅ 保留 DeerFlow | DeerFlow LangGraph Server (port 2024) | Agent 运行时和工作流执行 |
| Nginx 反向代理 | ✅ 保留 DeerFlow | DeerFlow Nginx (port 2026) | 统一入口，路由分发 |
| SSE 流式输出 | ✅ 保留 DeerFlow | DeerFlow LangGraph SSE 协议 | values/messages-tuple/end + 子代理 SSE 事件 |
| Web 前端（Next.js） | ✅ 保留 DeerFlow（需定制） | DeerFlow `frontend/` | 保留框架，砍掉 DeerFlow 特有的 UI 元素（如 Flash/Pro/Ultra 模式选择），改为通用企业 UI |
| 嵌入式客户端 | ✅ 保留 DeerFlow | DeerFlow `DeerFlowClient` | Python 进程内直接调用，可作为 SDK 嵌入其他应用 |
| IM 渠道（Telegram/Slack/飞书） | 🔴 砍掉 | DeerFlow `app/channels/` | SmartFlow 定位：对外提供 API，对内 Web UI 访问。不需要 IM 渠道集成 |
| 文件上传/文档转换 | ✅ 保留 DeerFlow | DeerFlow uploads + markitdown | PDF/PPT/Excel/Word → Markdown 自动转换 |

**前端定制方向：**
- 砍掉 DeerFlow 的 Flash/Standard/Pro/Ultra 模式选择 UI
- 增加 Capability Pack 选择（用户选择业务场景）
- 增加成本仪表盘（Token 消耗统计）
- 增加管理后台（Skills/MCP/模型配置管理）
- 增加决策审计查看界面


---

### 第 8 层：部署与运维层

| 模块 | 决策 | 来源 | 理由 |
|------|------|------|------|
| Docker Compose（dev+prod） | ✅ 保留 DeerFlow | DeerFlow `docker/` | 开发和生产两套 compose 配置 |
| Dockerfile | ✅ 保留 DeerFlow | DeerFlow `backend/Dockerfile` + `frontend/Dockerfile` | 前后端独立构建 |
| Nginx 配置 | ✅ 保留 DeerFlow | DeerFlow `docker/nginx/` | 统一反向代理 |
| K8s Provisioner | ✅ 保留 DeerFlow | DeerFlow `docker/provisioner/` | 沙箱 Pod 管理 |
| 配置热重载 | ✅ 保留 DeerFlow | DeerFlow config.yaml mtime 检测 + MCP mtime 缓存失效 | 自动重载，不需重启 |
| 配置版本管理 | ✅ 保留 DeerFlow | DeerFlow `config_version` + `make config-upgrade` | 配置升级迁移 |
| 健康检查 | ✅ 保留 DeerFlow | DeerFlow Gateway `/health` | 基础健康检查 |
| Harness/App 分层 | ✅ 保留 DeerFlow | DeerFlow `packages/harness/` vs `app/` | 框架包与应用层严格分离，CI 边界测试 |
| **成本预算控制** | 🔴 需新增，自研 | 参考行业实践 | 每 Agent/每用户/每日 Token 预算限制，超限自动降级或拒绝 |
| **语义缓存** | 🟡 后续新增，自研 | 参考行业实践 | 相同/相似请求复用 LLM 响应，降低成本 |

---

## 总结：模块来源统计

| 来源 | 模块数 | 占比 | 说明 |
|------|--------|------|------|
| ✅ 保留 DeerFlow | 约 32 个 | ~65% | DeerFlow 的核心架构、沙箱、Guardrail、API、UI、部署 |
| 🔴 借鉴 SmartClaw | 约 10 个 | ~20% | Fallback Chain、多级压缩、Capability Pack、OTEL、审计、脱敏、循环检测、Bootstrap |
| 🔴 需自研 | 约 3 个 | ~7% | RAG、成本追踪/预算 |
| 🟡 后续迭代 | 约 3 个 | ~7% | Orchestrator 动态编排、Debug UI、语义缓存 |
| 🔴 砍掉 | 约 11 个 | — | 6 个内置 Skills + 图片搜索工具 + CLI Provider + 3 个 IM 渠道 |

---

## 开发优先级路线图

### Phase 1：最小可用（4-6 周）

以 DeerFlow 为底座，做减法 + 最小增量：

1. Fork DeerFlow 2.0，砍掉内置 Skills（保留框架机制）
2. 砍掉 DuckDuckGo 图片搜索、CLI Provider、IM 渠道模块（Telegram/Slack/飞书）
3. 新增 Bootstrap 引导系统（SOUL.md/USER.md/TOOLS.md）
4. 新增结构化日志（structlog 替换 logging）
5. 新增 ToolResultGuard（L1 上下文压缩）
6. 前端去掉 DeerFlow 特有 UI，改为通用企业界面
7. 项目重命名、品牌定制

产出：一个干净的、可配置的企业 Agent 框架，能通过 Skill + MCP 扩展业务。

### Phase 2：核心增强（6-8 周）

补齐生产级必备能力：

1. Fallback Chain（借鉴 SmartClaw）
2. SessionPruner（L2 上下文压缩）
3. Capability Pack 场景级治理（借鉴 SmartClaw）
4. OTEL 分布式追踪
5. 成本追踪 + Token 预算控制
6. 敏感数据脱敏
7. 路径安全策略

产出：具备 LLM 容错、安全治理、可观测性的生产级框架。

### Phase 3：深度完善（8-12 周）

补齐竞争力差异化能力：

1. RAG/知识库集成（ContextEngine 插件）
2. Decision Record 审计
3. 循环检测
4. 诊断事件总线 + Debug UI
5. 管理后台（Skills/MCP/模型/成本仪表盘）

产出：功能完整的企业级多 Agent 框架。

### Phase 4：前瞻布局（持续迭代）

1. Orchestrator 动态编排（借鉴 SmartClaw 五阶段）
2. 自动模式路由
3. 语义缓存
4. A2A 协议支持
5. 多租户与权限体系
