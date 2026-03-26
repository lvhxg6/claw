# SmartClaw 技术路线

## 项目定位

| 项目 | 说明 |
|------|------|
| 名称 | SmartClaw |
| 语言 | Python 3.12+ |
| 定位 | 工程生产级 AI Agent，核心聚焦浏览器操作 |
| 应用场景 | Web 调研、自动化测试、RPA |
| 参考架构 | PicoClaw（模块设计）、OpenClaw（生产级实践）、Browser Use（浏览器 Agent 架构） |

---

## 技术选型依据

### 为什么选 Python？

| 维度 | Go | Python | 结论 |
|------|-----|--------|------|
| 浏览器操作（核心需求） | 4/10 | 10/10 | Python 碾压 |
| Agent 框架生态 | 5/10 | 9/10 | Python 成熟 |
| LLM 接入 | 7/10 | 9/10 | Python 更便捷 |
| MCP 协议 | 8/10 | 8/10 | 持平 |
| 记忆/RAG | 5/10 | 9/10 | Python 开箱即用 |
| 工程生产级 | 9/10 | 6/10 | Go 更优 |
| 自动化测试场景 | 4/10 | 9/10 | Python 生态成熟 |
| 开发效率 | 5/10 | 9/10 | Python 快 2-3 倍 |

核心需求（浏览器操作、自动化测试）是 Go 生态最薄弱的地方，Python 有压倒性优势。

### 浏览器 Agent 赛道现状

| 项目 | 语言 | GitHub Stars | 浏览器引擎 | 特点 |
|------|------|-------------|-----------|------|
| Browser Use | Python | 78,000+ | Playwright | 最主流，LangChain 集成 |
| Stagehand | TypeScript | 21,000+ | Playwright | TS 开发者友好 |
| Skyvern | Python | 20,000+ | Playwright | 无代码工作流 |
| Agent Browser | Python | 14,000+ | Playwright | CLI 优先 |
| Steel Browser | TypeScript | 6,400+ | Playwright | 浏览器沙箱基础设施 |
| Go 方案 | Go | 几乎没有 | Rod/chromedp | 无成熟 AI Browser Agent |

所有主流 Browser Agent 都使用 Playwright，核心原因：
- 支持多浏览器（Chrome/Firefox/WebKit）
- 原生 Accessibility Tree 支持（LLM 理解页面的关键）
- 社区活跃，生态成熟

---

## 技术选型

### 选型总表

| # | 模块 | 选型 | 版本 | 参考来源 |
|---|------|------|------|---------|
| 1 | Agent 编排 | LangGraph StateGraph | >= 0.4 | PicoClaw `pkg/agent/loop.go` |
| 2 | LLM 接入 | LangChain ChatModel | >= 0.3 | PicoClaw `pkg/providers/` |
| 3 | 默认模型 | Kimi 2.5（多模态 Vision） | 备选 GPT-4o / Claude Sonnet 4 | - |
| 4 | 浏览器引擎 | Playwright + CDP 双模式 | 最新版 | Browser Use 架构 + OpenClaw `src/browser/` |
| 5 | 页面理解 | Accessibility Tree 为主 + 截图为辅 | - | OpenClaw `pw-role-snapshot.ts` |
| 6 | 工具系统 | LangChain Tools + 自定义 | - | PicoClaw `pkg/tools/` |
| 7 | 工具注册 | LangChain Tools 注册机制 | - | PicoClaw `pkg/tools/registry.go` |
| 8 | Web 搜索 | tavily-python | 最新版 | PicoClaw `pkg/tools/search_tool.go` |
| 9 | MCP 协议 | 官方 mcp Python SDK | >= 2.1 | PicoClaw `pkg/mcp/manager.go` |
| 10 | MCP 传输 | stdio 为主，Streamable HTTP 为辅 | - | PicoClaw MCP 配置 |
| 11 | 记忆存储 | SQLite（LangGraph SqliteSaver） | - | PicoClaw `pkg/memory/` |
| 12 | 向量数据库 | sqlite-vec + langchain-community | 最新版 | OpenClaw `src/memory/sqlite-vec.ts` |
| 13 | 配置格式 | YAML + Pydantic Settings | - | OpenClaw YAML + Zod Schema |
| 14 | API 网关 | FastAPI + uvicorn | - | PicoClaw `pkg/gateway/` |
| 15 | 日志 | structlog | - | PicoClaw `pkg/logger/` |
| 16 | 可观测性 | OpenTelemetry（可选） | - | OpenClaw `diagnostics-otel` |
| 17 | HTTP 客户端 | httpx | - | - |
| 18 | 定时任务 | APScheduler | - | PicoClaw `pkg/cron/` |
| 19 | 凭证管理 | python-dotenv + keyring | - | PicoClaw `pkg/credential/` |
| 20 | Skills 系统 | YAML + importlib 动态加载 | - | PicoClaw `pkg/skills/` |
| 21 | Sub-Agent | LangGraph SubGraph | - | PicoClaw `subturn.go` + OpenClaw `subagent-*.ts` |
| 22 | 多 Agent | LangGraph Multi-Agent | - | PicoClaw Agent 绑定机制 |
| 23 | Hook 系统 | asyncio 事件模式（自研） | - | OpenClaw `src/hooks/` |
| 24 | 插件体系 | pluggy / entry_points | - | OpenClaw `src/plugins/` Plugin SDK |
| 25 | 安全-路径策略 | pathlib 白名单/黑名单 | - | PicoClaw 工具层路径验证 |
| 26 | 安全-工具策略 | 自研 tool_policy | - | OpenClaw `tool-policy.ts` |
| 27 | 安全-审计日志 | structlog 结构化审计 | - | OpenClaw `src/security/audit.ts` |
| 28 | 包管理 | uv | pyproject.toml + uv.lock | - |
| 29 | 测试 | pytest + pytest-asyncio + pytest-playwright | - | - |
| 30 | 类型检查 | mypy | - | - |
| 31 | Linter | ruff | - | - |

### 关键选型决策说明

1. **Agent 框架选 LangGraph**：LangChain AgentExecutor 已废弃（维护到 2026.12），LangGraph StateGraph 是官方推荐替代。
2. **浏览器自研而非直接用 Browser Use**：Browser Use 正从 Playwright 迁移到原生 CDP，API 不稳定。参考其架构自研更可控。
3. **Playwright + CDP 双模式**：OpenClaw 实践验证，某些场景（超时控制、代理绕过）需要 CDP 直接操作。Playwright Python 原生支持 `CDPSession`。
4. **A11y Tree 为主**：比截图快 10-100 倍，Token 消耗少 10-100 倍。OpenClaw 和 Playwright MCP 都采用此方案。
5. **sqlite-vec 而非 ChromaDB**：OpenClaw 实践验证，与记忆存储统一 SQLite，零额外进程。LangChain 已有官方集成。
6. **YAML 配置**：Python 生态主流（Docker Compose、K8s），支持注释。OpenClaw 也用 YAML。
7. **uv 包管理**：比 pip 快 100 倍，2026 年 Python 社区推荐标准。

---

## 项目结构

```
smartclaw/
├── smartclaw/
│   ├── __init__.py
│   ├── main.py                      # 入口
│   ├── agent/                       # Agent 编排（参考 PicoClaw pkg/agent/）
│   │   ├── graph.py                 # LangGraph 主图
│   │   ├── state.py                 # Agent 状态定义
│   │   ├── nodes.py                 # 推理/行动/观察节点
│   │   ├── router.py               # 模型路由
│   │   └── subagent.py             # Sub-Agent 编排
│   ├── browser/                     # 浏览器引擎（参考 Browser Use + OpenClaw）
│   │   ├── engine.py                # Playwright 引擎管理
│   │   ├── cdp.py                   # CDP 底层操作
│   │   ├── page_parser.py           # 页面理解（A11y Tree + DOM）
│   │   ├── actions.py               # 浏览器动作
│   │   ├── screenshot.py            # 截图和视觉理解
│   │   └── session.py               # 会话/Tab 管理
│   ├── tools/                       # 工具系统（参考 PicoClaw pkg/tools/）
│   │   ├── base.py                  # 工具基类
│   │   ├── registry.py              # 工具注册中心
│   │   ├── browser_tools.py         # 浏览器工具集
│   │   ├── filesystem.py            # 文件操作
│   │   ├── shell.py                 # 命令执行
│   │   ├── web_search.py            # Web 搜索
│   │   └── mcp_tool.py              # MCP 工具桥接
│   ├── providers/                   # LLM 接入（参考 PicoClaw pkg/providers/）
│   │   ├── factory.py               # Provider 工厂
│   │   ├── config.py                # 模型配置
│   │   └── fallback.py              # Fallback 和负载均衡
│   ├── mcp/                         # MCP 协议（参考 PicoClaw pkg/mcp/）
│   │   └── manager.py               # MCP Server 管理器
│   ├── skills/                      # Skills 系统（参考 PicoClaw pkg/skills/）
│   │   ├── loader.py                # 技能加载器
│   │   ├── registry.py              # 技能注册表
│   │   └── installer.py             # 技能安装器
│   ├── memory/                      # 记忆系统（参考 PicoClaw + OpenClaw）
│   │   ├── store.py                 # SQLite 记忆存储
│   │   ├── rag.py                   # sqlite-vec RAG 检索
│   │   └── summary.py              # 自动摘要
│   ├── config/                      # 配置管理（参考 OpenClaw）
│   │   ├── settings.py              # Pydantic Settings
│   │   └── schema.py                # 配置 Schema
│   ├── gateway/                     # API 网关（参考 PicoClaw pkg/gateway/）
│   │   └── api.py                   # FastAPI REST API
│   ├── hooks/                       # Hook 系统（参考 OpenClaw src/hooks/）
│   │   ├── lifecycle.py             # 生命周期 Hook
│   │   ├── loader.py                # Hook 加载注册
│   │   └── types.py                 # Hook 类型定义
│   ├── security/                    # 安全体系（参考 OpenClaw src/security/）
│   │   ├── path_policy.py           # 路径策略
│   │   ├── tool_policy.py           # 工具策略
│   │   └── audit.py                 # 审计日志
│   └── observability/               # 可观测性（参考 OpenClaw diagnostics-otel）
│       ├── logging.py               # structlog 结构化日志
│       └── tracing.py               # OpenTelemetry 追踪
├── plugins/                         # 插件目录（参考 OpenClaw Plugin SDK）
├── config/
│   └── config.example.yaml
├── tests/
├── pyproject.toml
├── README.md
└── Makefile
```

---

## 核心依赖

```toml
[project]
name = "smartclaw"
requires-python = ">=3.12"

[project.dependencies]
# Agent 框架
langgraph = ">=0.4"
langchain = ">=0.3"
langchain-openai = "*"
langchain-anthropic = "*"
# 浏览器
playwright = "*"
# MCP
mcp = ">=2.1"
# API
fastapi = "*"
uvicorn = "*"
# 配置
pydantic-settings = "*"
pyyaml = "*"
# 记忆/RAG
sqlite-vec = "*"
langchain-community = "*"
# 日志
structlog = "*"
# HTTP
httpx = "*"
# 工具
tavily-python = "*"
apscheduler = "*"
python-dotenv = "*"
keyring = "*"
# 插件
pluggy = "*"

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-playwright",
    "mypy",
    "ruff",
]
```

---

## 开发路线图

### P0：核心 MVP（第 1-4 周）✅ 已完成

目标：完整可用的浏览器 Agent，能通过 LLM 驱动浏览器完成任务，支持 MCP 工具生态

**完成状态：** 全部完成。8 个系统工具（read_file, write_file, edit_file, append_file, list_directory, exec_command, web_search, web_fetch）、15 个浏览器工具、MCP 协议管理器、LLM Fallback Chain、配置管理、安全路径策略均已实现并通过测试。

| 任务 | 涉及选型 | 实现方案 | 参考来源 |
|------|---------|---------|---------|
| 项目初始化 | #28 包管理、#30 类型检查、#31 Linter | uv + pyproject.toml + mypy + ruff | - |
| 日志系统 | #15 日志 | structlog 结构化日志 | PicoClaw `pkg/logger/` |
| LLM 接入 | #2 LLM 接入、#3 默认模型、#17 HTTP | LangChain ChatModel（Kimi 2.5），httpx | PicoClaw `pkg/providers/` |
| Agent 主循环 | #1 Agent 编排 | LangGraph ReAct StateGraph | PicoClaw `pkg/agent/loop.go` |
| 浏览器引擎 | #4 浏览器引擎 | Playwright 初始化、导航、基础操作 | Browser Use + OpenClaw `src/browser/` |
| 页面理解 | #5 页面理解 | Accessibility Tree 解析 → LLM 可理解文本 | OpenClaw `pw-role-snapshot.ts` |
| 浏览器工具集 | #6 工具系统 | navigate/click/type/scroll/screenshot | Browser Use 工具设计 |
| 工具注册框架 | #7 工具注册 | LangChain Tools 注册机制 | PicoClaw `pkg/tools/registry.go` |
| 文件系统工具 | #6 工具系统 | pathlib 封装 | PicoClaw `pkg/tools/filesystem.go` |
| Shell 工具 | #6 工具系统 | asyncio.subprocess | PicoClaw `pkg/tools/shell.go` |
| Web 搜索工具 | #8 Web 搜索 | tavily-python | PicoClaw `pkg/tools/search_tool.go` |
| MCP 管理器 | #9 MCP 协议、#10 MCP 传输 | mcp Python SDK，stdio + Streamable HTTP | PicoClaw `pkg/mcp/manager.go` |
| 配置管理 | #13 配置格式 | Pydantic Settings + YAML | OpenClaw YAML + Zod Schema |
| 凭证管理 | #19 凭证管理 | python-dotenv + keyring | PicoClaw `pkg/credential/` |
| 基础安全 | #25 路径策略 | pathlib 路径白名单 + 敏感数据过滤 | PicoClaw 工具层路径验证 |

里程碑：输入自然语言任务，Agent 能自动打开浏览器完成，支持 MCP 调用外部工具，YAML 配置驱动。

### P1：增强能力（第 5-6 周）✅ 已完成

目标：Skills 技能体系、Sub-Agent 任务分解、跨会话记忆

**完成状态：** 全部完成。6 个模块已实现：
- **MemoryStore** — aiosqlite 持久化，跨会话记忆，完整消息类型支持（HumanMessage/AIMessage/ToolMessage）
- **AutoSummarizer** — LLM 驱动的双阈值自动摘要（消息数 + token 百分比），force_compression 支持
- **SkillsLoader** — YAML + SKILL.md 双格式，workspace/global/builtin 三级目录，优先级覆盖
- **SkillsRegistry** — 动态注册到 ToolRegistry，支持 Python 函数工具 + Native Command 工具 + Markdown 提示词工具
- **SubAgent** — LangGraph SubGraph + asyncio.Semaphore 并发控制，深度限制，超时保护
- **MultiAgentCoordinator** — Supervisor 模式多 Agent 协同

**额外完成（P1 补充）：**
- **Native Command Skills** — shell/script/exec 三种命令工具类型，asyncio subprocess 执行
- **SKILL.md 格式** — Markdown 提示词技能（YAML frontmatter + body），{param_name}/{skill_dir}/{workspace} 占位符替换
- **scripts/ 自动发现** — 约定大于配置，scripts/ 子目录自动扫描 .sh/.py/.js/.mjs/.ts/.rb/.pl/.go 文件
- **CLI 全功能** — 零配置启动，所有特性默认开启，斜杠命令（/history /summary /clear /tools /help /quit），工具调用追踪

**测试覆盖：** 638+ 单元测试（含属性测试），12/12 基础场景，14/16 跨功能场景，15/16 全功能集成测试。

| 任务 | 涉及选型 | 实现方案 | 参考来源 |
|------|---------|---------|---------|
| Skills 加载器 | #20 Skills 系统 | YAML 定义 + importlib 动态加载 | PicoClaw `pkg/skills/loader.go` |
| Skills 注册表 | #20 Skills 系统 | 技能发现和管理 | PicoClaw `pkg/skills/registry.go` |
| Sub-Agent | #21 Sub-Agent | LangGraph SubGraph 任务委托 | PicoClaw `subturn.go` + OpenClaw `subagent-*.ts` |
| 记忆存储 | #11 记忆存储 | SQLite 持久化（SqliteSaver） | PicoClaw `pkg/memory/` |
| 自动摘要 | #11 记忆存储 | LLM 长对话摘要压缩 | PicoClaw Agent 配置 |
| 多 Agent 协同 | #22 多 Agent | LangGraph Multi-Agent 编排 | PicoClaw Agent 绑定机制 |

里程碑：能分解复杂任务给 Sub-Agent，跨会话记忆保持，Skills 技能可复用。

### P2：生产级增强（第 7-9 周）⏳ 待开始

目标：RAG 知识增强、完整安全体系、可观测性、插件化

**优先级排序（已确认）：**
1. API 网关（FastAPI）— 让 SmartClaw 能作为服务运行，不只是 CLI
2. 生命周期 Hook — before/after tool call，对调试和安全审计关键
3. 可观测性 — OpenTelemetry，生产环境必备
4. RAG、插件体系、定时任务等后续再做

| 任务 | 涉及选型 | 实现方案 | 参考来源 |
|------|---------|---------|---------|
| RAG 系统 | #12 向量数据库 | sqlite-vec + LangChain 文档索引检索 | OpenClaw `src/memory/sqlite-vec.ts` |
| 生命周期 Hook | #23 Hook 系统 | asyncio 事件（before/after tool call） | OpenClaw `src/hooks/` |
| 安全-工具策略 | #26 工具策略 | 自研 tool_policy | OpenClaw `tool-policy.ts` |
| 安全-审计日志 | #27 审计日志 | structlog 结构化审计 | OpenClaw `src/security/audit.ts` |
| 插件体系 | #24 插件体系 | pluggy/entry_points，Provider 插件化 | OpenClaw `src/plugins/` |
| 可观测性 | #16 可观测性 | OpenTelemetry 分布式追踪 | OpenClaw `diagnostics-otel` |
| CDP 增强 | #4 浏览器引擎 | CDPSession 超时控制、代理绕过 | OpenClaw `cdp-timeouts.ts` |
| API 网关 | #14 API 网关 | FastAPI REST API | PicoClaw `pkg/gateway/` |
| 定时任务 | #18 定时任务 | APScheduler | PicoClaw `pkg/cron/` |

里程碑：生产可用，完整的安全、可观测性和插件体系。

### 贯穿全阶段

| 涉及选型 | 实现方案 | 说明 |
|---------|---------|------|
| #29 测试 | pytest + pytest-asyncio + pytest-playwright | 每个阶段同步编写单元测试和集成测试 |

---

## 风险点和应对

| 风险 | 影响 | 应对方案 |
|------|------|---------|
| Browser Use API 不稳定（迁移到 CDP） | 高 | 参考架构自研，不直接依赖 |
| Playwright 浏览器资源泄漏 | 高 | 会话池管理、超时清理、进程监控 |
| sqlite-vec 生态较新 | 中 | LangChain 已有官方集成，ChromaDB 作为备选 |
| Python 生产部署环境依赖多 | 中 | Docker 容器化，uv.lock 固定版本 |
| Playwright 镜像体积大（500MB+） | 低 | 多阶段构建，只装 Chromium |
| Skills 系统无现成 Python 方案 | 低 | 参考 PicoClaw 设计，YAML + importlib |
| 动态语言长期维护 | 中 | mypy 严格类型标注 + ruff + 测试覆盖 |

---

## OpenClaw 对比分析与选型验证

基于对 OpenClaw（TypeScript/Node.js）源码的深入分析，验证和调整了以下技术选型：

| 维度 | OpenClaw 实际实现 | SmartClaw 选型 |
|------|-----------------|---------------|
| 语言 | TypeScript/Node.js | Python |
| Agent 框架 | 完全自研（src/agents/ 400+ 文件） | LangGraph StateGraph |
| 浏览器引擎 | Playwright + CDP 双模式（120+ 文件） | Playwright + CDP 双模式 |
| 页面理解 | Accessibility Tree（pw-role-snapshot.ts） | A11y Tree 为主 + 截图为辅 |
| LLM 接入 | 自研 Provider + extensions/ 80+ 提供商 | LangChain ChatModel |
| MCP | 自研集成（mcp-stdio.ts、chrome-mcp.ts） | 官方 mcp Python SDK |
| Skills | 完整系统（skills/ 50+ 技能） | 自研，参考 PicoClaw |
| Sub-Agent | 完整系统（subagent-*.ts 20+ 文件） | LangGraph SubGraph |
| 记忆系统 | sqlite-vec + 多 Embedding 提供商（100+ 文件） | SQLite + sqlite-vec |
| 配置管理 | YAML + Zod Schema（200+ 文件） | YAML + Pydantic Settings |
| 安全 | 分层安全（src/security/ 35+ 文件） | 分层安全（路径 + 工具 + 审计） |
| Hook 系统 | 生命周期 Hook（src/hooks/ 40+ 文件） | 生命周期 Hook |
| 插件体系 | Plugin SDK（src/plugins/ 150+ 文件） | pluggy / entry_points |
| 可观测性 | OTEL 扩展（diagnostics-otel） | structlog + OpenTelemetry |

### 基于 OpenClaw 的选型调整

| 调整项 | 调整前 | 调整后 | OpenClaw 验证 |
|--------|--------|--------|-------------|
| 向量数据库 | ChromaDB | sqlite-vec | OpenClaw 用 sqlite-vec，更轻量，统一 SQLite |
| 浏览器引擎 | 纯 Playwright | Playwright + CDP 预留 | OpenClaw 双模式，某些场景需要 CDP 直接操作 |
| 插件体系 | 无 | 第二阶段增加 | OpenClaw 扩展性完全依赖插件体系 |
| Hook 系统 | 简单审批 | 生命周期 Hook | OpenClaw 支持多个生命周期节点 |
| 安全体系 | 基础路径限制 | 分层安全 | OpenClaw 有 tool-policy + audit 完整体系 |

---

## 参考资料

| 参考项目 | 语言 | 参考内容 |
|---------|------|---------|
| [PicoClaw](../picoclaw/) | Go | Agent 编排、LLM 接入、工具系统、MCP、Skills、记忆、路由 |
| [OpenClaw](../openclaw/) | TypeScript | 浏览器 CDP、页面理解、sqlite-vec、配置校验、Hook、插件、安全、可观测性 |
| [Browser Use](https://github.com/browser-use/browser-use) | Python | 浏览器 Agent 整体架构设计（78K+ stars） |

| 技术文档 | 链接 |
|---------|------|
| AI Agent 架构设计 | [agent-architecture.zh.md](./agent-architecture.zh.md) |
| PicoClaw vs ZeroClaw 能力对比 | [agent-capability-analysis.zh.md](./agent-capability-analysis.zh.md) |
| LangGraph | https://github.com/langchain-ai/langgraph |
| Playwright Python | https://playwright.dev/python/ |
| Playwright CDP API | https://playwright.dev/python/docs/api/class-cdpsession |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| sqlite-vec | https://github.com/asg017/sqlite-vec |
| LangChain SQLiteVec | https://python.langchain.com/docs/integrations/vectorstores/sqlitevec/ |
| pluggy | https://pluggy.readthedocs.io/ |
