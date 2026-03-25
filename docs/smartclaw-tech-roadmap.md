# SmartClaw 技术路线

## 项目定位

- **名称**：SmartClaw
- **语言**：Python
- **定位**：工程生产级别的 AI Agent，类 OpenClaw
- **核心能力**：浏览器操作（Browser Use）
- **应用场景**：Web 调研、自动化测试、RPA
- **参考架构**：PicoClaw（Go）模块设计
- **浏览器引擎**：Playwright（行业标准，Browser Use 78K+ stars 验证）

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

## 具体技术选型

### 1. Agent 框架：LangGraph StateGraph

| 选项 | 状态 | 结论 |
|------|------|------|
| LangChain AgentExecutor | ❌ 已废弃，维护到 2026.12 | 不选 |
| LangGraph StateGraph | ✅ 官方推荐替代方案 | **选定** |
| 自研 ReAct 循环 | 无必要造轮子 | 不选 |

LangChain 官方已明确 AgentExecutor 进入维护模式，新项目应使用 LangGraph 的 `StateGraph`。
LangGraph 支持循环、重试、条件分支、人机协同，匹配 SmartClaw 全部需求。

选型：`langgraph >= 0.4`，使用 `StateGraph` 自定义编排。

### 2. 浏览器能力：Playwright + 参考 Browser Use 架构自研

| 选项 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| 直接依赖 Browser Use 库 | 开箱即用 | 正在从 Playwright 迁移到原生 CDP，API 不稳定 | 不选 |
| 参考 Browser Use 架构自研 | 可控、稳定 | 工作量稍大 | **选定** |
| 原生 CDP | 性能最好 | 太底层，开发成本高 | 不选 |

关键发现：Browser Use 官方博客宣布正在从 Playwright 迁移到原生 CDP，API 会有大变动，直接依赖有风险。
选型：参考 Browser Use 架构思路自研浏览器模块，底层用 Playwright + CDP 双模式。

> **OpenClaw 验证**：OpenClaw 的 `src/browser/` 模块（120+ 文件）同时支持 Playwright 高级 API 和原生 CDP 底层操作（`cdp.ts`、`cdp-timeouts.ts`、`cdp-proxy-bypass.ts`），证明双模式是生产级项目的正确选择。Playwright Python 原生支持 `CDPSession`，通过 `browser.new_cdp_session(page)` 即可获取 CDP 会话。

#### 页面理解方式：DOM/A11y Tree 为主 + 截图为辅

| 方式 | 速度 | 成本 | 准确度 | Token 消耗 |
|------|------|------|--------|-----------|
| DOM/Accessibility Tree | 快（2-5KB） | 低 | 高（精确定位元素） | 少 |
| 截图 + Vision | 慢（500KB-2MB） | 高（~$0.01/步） | 中（坐标可能偏移） | 多（10-100x） |
| 两者结合 | 中 | 中 | 最高 | 中 |

调研结论：DOM/A11y Tree 方式比截图快 10-100 倍，Token 消耗少 10-100 倍。
Browser Use 和 Playwright MCP 都以 A11y Tree 为主。

选型：Accessibility Tree 为主，截图为辅（复杂页面或调试时使用）。

### 3. LLM 接入

| 决策点 | 选型 | 理由 |
|--------|------|------|
| 默认模型 | GPT-4o | 性价比最高，多模态支持好，Browser Use 默认用它 |
| 备选模型 | Claude Sonnet 4 | 推理能力强，适合复杂任务 |
| 本地模型（Ollama） | 第一阶段不支持 | Ollama 的 Vision 能力弱，浏览器场景不适合 |
| 多模态（Vision） | 第一阶段就支持 | 浏览器截图理解需要 Vision 能力 |
| 接入方式 | LangChain ChatModel | 统一接口，切换模型零成本 |

### 4. 存储

#### 记忆存储

| 选项 | 适合场景 | 结论 |
|------|---------|------|
| SQLite | 单机部署，结构化查询 | **选定** |
| JSON 文件 | 最简单 | ❌ 查询能力弱 |
| Redis | 分布式，高并发 | ❌ 第一阶段过重 |

选型：SQLite，通过 LangGraph 的 `SqliteSaver` 集成。

#### RAG 向量数据库

| 选项 | 特点 | 结论 |
|------|------|------|
| sqlite-vec | SQLite 向量扩展，零依赖，LangChain 官方集成 | **选定** |
| ChromaDB | 嵌入式，适合原型 | 备选 |
| FAISS | 库不是数据库，无持久化/API | ❌ 不适合生产 |
| Milvus | 重量级，适合大规模 | ❌ 第一阶段过重 |

选型：sqlite-vec，和记忆存储统一使用 SQLite，无需额外进程。

> **OpenClaw 验证**：OpenClaw 的记忆系统使用 sqlite-vec（`src/memory/sqlite-vec.ts`），而非 ChromaDB 或其他独立向量数据库。LangChain Python 已有官方 SQLiteVec 集成（`langchain-community`）。

### 5. MCP 协议

| 决策点 | 选型 | 理由 |
|--------|------|------|
| SDK | 官方 mcp Python SDK | 官方维护，97M+ 下载量 |
| SDK 版本 | >= 2.1（对应 MCP spec 1.3） | 最新稳定版，支持 Streamable HTTP |
| Python 版本要求 | >= 3.12 | MCP SDK 2.1 要求 |
| 传输方式 | stdio 优先 | 本地工具最简单；远程服务用 Streamable HTTP |

### 6. 配置格式：YAML

| 选项 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| JSON | PicoClaw 用的，严格 | 不支持注释，可读性差 | 不选 |
| YAML | 支持注释，可读性好，Python 生态主流 | 缩进敏感 | **选定** |
| TOML | 简洁，Rust/Python 新项目偏好 | 嵌套结构表达不如 YAML | 不选 |

选型：YAML + Pydantic Settings 做校验。Python 生态主流（Docker Compose、Ansible、K8s 都用 YAML）。

### 7. 项目管理

#### 包管理器

| 选项 | 速度 | 成熟度 | 结论 |
|------|------|--------|------|
| pip | 慢 | 最成熟 | ❌ 无 lock 文件，不适合生产 |
| poetry | 中 | 成熟（5 年） | 备选 |
| uv | 极快（100x pip） | Astral 团队（Ruff）出品，Rust 实现 | **选定** |

调研结论：uv 安装速度比 pip 快 10-100 倍，CI/CD 时间减少 50-80%，2026 年已是 Python 社区推荐标准。

选型：`uv`，使用 `pyproject.toml` + `uv.lock`。

#### Python 版本

| 版本 | 结论 |
|------|------|
| 3.11 | ❌ MCP SDK 2.1 要求 3.12+ |
| 3.12 | **选定**，MCP SDK 最低要求，稳定 |
| 3.13 | 备选，较新 |

### 技术选型汇总

| 决策项 | 选型 | 版本/备注 |
|--------|------|----------|
| Agent 框架 | LangGraph StateGraph | >= 0.4 |
| 浏览器引擎 | Playwright + CDP 双模式（参考 Browser Use 架构自研） | 最新版 |
| 页面理解 | Accessibility Tree 为主 + 截图为辅 | - |
| 默认 LLM | GPT-4o（LangChain 接入） | 备选 Claude Sonnet 4 |
| 多模态 | 第一阶段支持 | Vision 能力 |
| 记忆存储 | SQLite | LangGraph SqliteSaver |
| 向量数据库 | sqlite-vec | LangChain SQLiteVec 集成 |
| MCP SDK | 官方 mcp Python SDK | >= 2.1 |
| MCP 传输 | stdio 为主，Streamable HTTP 为辅 | - |
| 配置格式 | YAML | Pydantic Settings 校验 |
| 包管理器 | uv | pyproject.toml + uv.lock |
| Python 版本 | 3.12+ | MCP SDK 要求 |
| API 框架 | FastAPI | - |
| 日志 | structlog | 结构化日志 |
| HTTP 客户端 | httpx | 异步支持 |
| 插件体系 | pluggy / entry_points | 第二阶段，参考 OpenClaw Plugin SDK |
| Hook 系统 | asyncio 事件模式 | 生命周期 Hook，参考 OpenClaw |
| 安全体系 | 分层安全（路径策略 + 工具策略 + 审计） | 参考 OpenClaw Security |

---

## PicoClaw 模块 → Python 技术选型映射

### 模块对标表

| PicoClaw 模块 | 文件数 | SmartClaw Python 对标 | 实现方式 |
|--------------|--------|---------------------|---------|
| pkg/agent/ (编排层) | 35 | LangGraph | 框架内置 ReAct/Planning/SubGraph |
| pkg/providers/ (LLM 接入) | 49 | LangChain ChatModel | 框架内置 30+ provider |
| pkg/tools/ (工具系统) | 44 | LangChain Tools + 自定义 | 框架内置 + 浏览器工具自研 |
| pkg/mcp/ (MCP 协议) | 2 | mcp-python-sdk | 官方 SDK |
| pkg/skills/ (Skills) | 10 | 自研（参考 PicoClaw 设计） | 技能加载/注册/市场 |
| pkg/memory/ (记忆) | 3 | LangGraph Checkpointer + LangChain Memory | 框架内置 |
| pkg/config/ (配置) | 多 | Pydantic Settings | 成熟方案 |
| pkg/logger/ (日志) | 少 | structlog / loguru | 成熟方案 |
| pkg/channels/ (渠道) | 93 | 暂不需要（聚焦浏览器） | 后期按需 |
| pkg/bus/ (事件总线) | 少 | Python asyncio Event | 内置 |
| pkg/session/ (会话) | 少 | LangGraph State | 框架内置 |
| pkg/routing/ (路由) | 少 | LangGraph 条件路由 | 框架内置 |
| pkg/gateway/ (API) | 少 | FastAPI | 成熟方案 |
| pkg/cron/ (定时任务) | 少 | APScheduler | 成熟方案 |
| pkg/credential/ (凭证) | 少 | python-dotenv + keyring | 成熟方案 |
| **新增：浏览器引擎** | 无 | Playwright + Browser Use 架构 | **核心差异化** |

### 自研量对比

| 维度 | PicoClaw (Go) | SmartClaw (Python) |
|------|--------------|-------------------|
| LLM 接入 | 49+ 文件自研 | ~1 个配置文件（LangChain 内置） |
| Agent 循环 | 35+ 文件自研 | ~3-5 个文件（LangGraph 编排） |
| 工具框架 | 44+ 文件自研 | ~5-10 个文件（框架 + 浏览器工具） |
| 记忆系统 | 3 文件自研 | ~2 个文件（框架内置） |
| MCP | 2 文件自研 | ~2 个文件（官方 SDK） |
| 浏览器能力 | 无 | ~10-15 个文件（核心自研） |

Python 自研量约为 PicoClaw 的 1/5，核心精力集中在浏览器能力上。

---

## 能力模块规划

### 第一阶段：MVP 核心（必须有）

| # | 能力模块 | PicoClaw 对标 | Python 实现方案 | 优先级 |
|---|---------|-------------|----------------|--------|
| 1 | LLM 接入层 | pkg/providers/ (49 文件) | LangChain ChatModel，内置 30+ provider | P0 |
| 2 | 工具调用系统 | pkg/tools/ (44 文件) | LangChain Tools + 自定义浏览器工具 | P0 |
| 3 | MCP 协议支持 | pkg/mcp/ (2 文件) | mcp-python-sdk 官方 SDK | P0 |
| 4 | 推理和规划（ReAct） | pkg/agent/loop.go | LangGraph 状态图，原生 ReAct 支持 | P0 |
| 5 | 记忆系统（基础） | pkg/memory/ (3 文件) | LangGraph Checkpointer | P0 |
| 6 | 配置管理 | pkg/config/ | Pydantic Settings | P0 |
| 7 | 基础安全 | pkg/tools/ 中的路径验证 | 路径限制 + 敏感数据过滤 | P0 |
| **8** | **浏览器引擎（核心）** | **无** | **Playwright + 页面理解 + 动作执行** | **P0** |

### 第二阶段：增强能力

| # | 能力模块 | PicoClaw 对标 | Python 实现方案 | 优先级 |
|---|---------|-------------|----------------|--------|
| 9 | Skills 系统 | pkg/skills/ (10 文件) | 自研，参考 PicoClaw 设计 | 高 |
| 10 | Sub-Agent | pkg/agent/subturn.go | LangGraph SubGraph | 高 |
| 11 | 多 Agent 协同 | Agent 绑定机制 | LangGraph Multi-Agent | 中 |
| 12 | 可观测性 | pkg/logger/ | structlog + OpenTelemetry（可选） | 中 |
| 13 | RAG/知识管理 | 无（PicoClaw 规划中） | LangChain + sqlite-vec | 中 |
| 14 | 人机协同 | Hook 系统 | 生命周期 Hook 系统（参考 OpenClaw） | 低 |
| 15 | 评估优化 | pkg/routing/ | LangGraph 条件路由 + 成本追踪 | 低 |
| 16 | 插件体系 | 无（参考 OpenClaw Plugin SDK） | pluggy / entry_points | 低 |
| 17 | 分层安全 | 无（参考 OpenClaw Security） | 路径策略 + 工具策略 + 审计日志 | 中 |

---

## 项目结构

```
smartclaw/
├── smartclaw/
│   ├── __init__.py
│   ├── main.py                      # 入口
│   │
│   ├── agent/                       # 对标 pkg/agent/（35 文件 → 5 文件）
│   │   ├── __init__.py
│   │   ├── graph.py                 # LangGraph 主图（对标 loop.go）
│   │   ├── state.py                 # Agent 状态定义（对标 context.go）
│   │   ├── nodes.py                 # 推理/行动/观察节点
│   │   ├── router.py               # 模型路由（对标 model_resolution.go）
│   │   └── subagent.py             # Sub-Agent 编排（对标 subturn.go）
│   │
│   ├── browser/                     # 新增：核心差异化模块（PicoClaw 无）
│   │   ├── __init__.py
│   │   ├── engine.py                # Playwright 浏览器引擎管理
│   │   ├── cdp.py                   # CDP 底层操作（参考 OpenClaw cdp.ts）
│   │   ├── page_parser.py           # 页面理解（Accessibility Tree + DOM 解析）
│   │   ├── actions.py               # 浏览器动作（点击/输入/滚动/导航等）
│   │   ├── screenshot.py            # 截图和视觉理解
│   │   └── session.py               # 浏览器会话/Tab 管理
│   │
│   ├── tools/                       # 对标 pkg/tools/（44 文件 → 8 文件）
│   │   ├── __init__.py
│   │   ├── base.py                  # 工具基类（对标 base.go + types.go）
│   │   ├── registry.py              # 工具注册中心（对标 registry.go）
│   │   ├── browser_tools.py         # 浏览器工具集（导航/点击/截图等）
│   │   ├── filesystem.py            # 文件操作（对标 filesystem.go）
│   │   ├── shell.py                 # 命令执行（对标 shell.go）
│   │   ├── web_search.py            # Web 搜索（对标 search_tool.go）
│   │   └── mcp_tool.py              # MCP 工具桥接（对标 mcp_tool.go）
│   │
│   ├── providers/                   # 对标 pkg/providers/（49 文件 → 3 文件）
│   │   ├── __init__.py
│   │   ├── factory.py               # Provider 工厂（对标 factory.go）
│   │   ├── config.py                # 模型配置和列表
│   │   └── fallback.py              # Fallback 和负载均衡（对标 fallback.go）
│   │
│   ├── mcp/                         # 对标 pkg/mcp/（2 文件 → 2 文件）
│   │   ├── __init__.py
│   │   └── manager.py               # MCP Server 管理器（对标 manager.go）
│   │
│   ├── skills/                      # 对标 pkg/skills/（10 文件 → 4 文件）
│   │   ├── __init__.py
│   │   ├── loader.py                # 技能加载器（对标 loader.go）
│   │   ├── registry.py              # 技能注册表（对标 registry.go）
│   │   └── installer.py             # 技能安装器（对标 installer.go）
│   │
│   ├── memory/                      # 对标 pkg/memory/（3 文件 → 3 文件）
│   │   ├── __init__.py
│   │   ├── store.py                 # 记忆存储（对标 jsonl.go）
│   │   ├── rag.py                   # RAG 检索增强（PicoClaw 无，新增）
│   │   └── summary.py               # 自动摘要
│   │
│   ├── config/                      # 对标 pkg/config/
│   │   ├── __init__.py
│   │   ├── settings.py              # Pydantic Settings 配置
│   │   └── schema.py                # 配置 Schema 定义
│   │
│   ├── gateway/                     # 对标 pkg/gateway/
│   │   ├── __init__.py
│   │   └── api.py                   # FastAPI REST API
│   │
│   ├── hooks/                       # 生命周期 Hook（参考 OpenClaw src/hooks/）
│   │   ├── __init__.py
│   │   ├── lifecycle.py             # before/after tool call、message hooks
│   │   ├── loader.py                # Hook 加载和注册
│   │   └── types.py                 # Hook 类型定义
│   │
│   ├── security/                    # 分层安全（参考 OpenClaw src/security/）
│   │   ├── __init__.py
│   │   ├── path_policy.py           # 路径白名单/黑名单策略
│   │   ├── tool_policy.py           # 工具调用权限策略
│   │   └── audit.py                 # 审计日志
│   │
│   └── observability/               # 对标 pkg/logger/ + 增强
│       ├── __init__.py
│       ├── logging.py               # 结构化日志（structlog）
│       └── tracing.py               # 分布式追踪（OpenTelemetry，可选）
│
├── plugins/                         # 插件目录（参考 OpenClaw Plugin SDK）
│   └── README.md                    # 插件开发指南
│
├── config/
│   └── config.example.yaml          # 配置示例
│
├── tests/                           # 测试
│   ├── test_agent/
│   ├── test_browser/
│   ├── test_tools/
│   └── test_providers/
│
├── pyproject.toml                   # 项目配置
├── README.md
└── Makefile                         # 构建脚本
```

---

## 核心依赖

```toml
[project]
name = "smartclaw"
requires-python = ">=3.12"

[project.dependencies]
# Agent 框架
langgraph = ">=0.4"                  # Agent 编排（StateGraph）
langchain = ">=0.3"                  # LLM 抽象层
langchain-openai = "*"               # OpenAI / GPT-4o
langchain-anthropic = "*"            # Anthropic / Claude Sonnet 4

# 浏览器引擎
playwright = "*"                     # 浏览器自动化（参考 Browser Use 架构自研）

# MCP
mcp = ">=2.1"                        # 官方 Python SDK（MCP spec 1.3）

# API
fastapi = "*"                        # REST API 网关
uvicorn = "*"                        # ASGI 服务器

# 配置
pydantic-settings = "*"              # 配置管理 + YAML 校验
pyyaml = "*"                         # YAML 解析

# 记忆/RAG
sqlite-vec = "*"                     # SQLite 向量扩展（替代 ChromaDB，参考 OpenClaw）
langchain-community = "*"            # LangChain SQLiteVec 集成

# 日志
structlog = "*"                      # 结构化日志

# HTTP 客户端
httpx = "*"                          # 异步 HTTP 客户端

# 定时任务
apscheduler = "*"                    # 定时任务调度
```

---

## 开发路线图

### P0 阶段：核心 MVP（第 1-2 周）

**目标**：能跑通 LLM + 浏览器操作的基本流程

| 任务 | 对标 PicoClaw | 说明 |
|------|-------------|------|
| 项目初始化 | - | pyproject.toml、目录结构、基础配置 |
| LLM 接入 | pkg/providers/ | LangChain ChatModel 配置，支持 OpenAI/Anthropic/Ollama |
| Agent 主循环 | pkg/agent/loop.go | LangGraph ReAct 状态图 |
| 浏览器引擎 | 无 | Playwright 初始化、页面导航、基础操作 |
| 页面理解 | 无 | Accessibility Tree 解析，转为 LLM 可理解的文本 |
| 浏览器工具集 | 无 | navigate/click/type/scroll/screenshot 工具 |

**里程碑**：输入"帮我搜索 xxx 并总结结果"，Agent 能自动打开浏览器完成任务。

### P1 阶段：工具和协议（第 3-4 周）

**目标**：完善工具体系，接入 MCP 生态

| 任务 | 对标 PicoClaw | 说明 |
|------|-------------|------|
| 工具注册框架 | pkg/tools/registry.go | 统一工具注册和发现 |
| 文件系统工具 | pkg/tools/filesystem.go | 文件读写操作 |
| Shell 工具 | pkg/tools/shell.go | 命令执行 |
| Web 搜索工具 | pkg/tools/search_tool.go | Brave/Tavily/DuckDuckGo 集成 |
| MCP 管理器 | pkg/mcp/manager.go | MCP Server 连接和工具调用 |
| 配置管理 | pkg/config/ | Pydantic Settings，YAML 配置 |
| 基础安全 | 工具层 | 路径限制、敏感数据过滤 |

**里程碑**：能通过 MCP 调用外部工具，配置文件驱动。

### P2 阶段：增强能力（第 5-6 周）

**目标**：Skills、Sub-Agent、记忆系统

| 任务 | 对标 PicoClaw | 说明 |
|------|-------------|------|
| Skills 加载器 | pkg/skills/loader.go | YAML 定义技能，动态加载 |
| Skills 注册表 | pkg/skills/registry.go | 技能发现和管理 |
| Sub-Agent | pkg/agent/subturn.go | LangGraph SubGraph，任务委托 |
| 记忆存储 | pkg/memory/jsonl.go | 会话记忆持久化 |
| 自动摘要 | Agent 配置 | 长对话自动摘要压缩 |
| 多 Agent 协同 | Agent 绑定 | LangGraph Multi-Agent 编排 |

**里程碑**：能分解复杂任务给 Sub-Agent，跨会话记忆保持。

### P3 阶段：生产级增强（第 7-9 周）

**目标**：RAG、可观测性、评估优化

| 任务 | 对标 PicoClaw | 说明 |
|------|-------------|------|
| RAG 系统 | 无（新增） | sqlite-vec + LangChain，文档索引和检索 |
| 可观测性 | pkg/logger/ | structlog 结构化日志 + OpenTelemetry（可选） |
| 评估优化 | pkg/routing/ | 模型路由（按复杂度选模型）、成本追踪 |
| 生命周期 Hook | 参考 OpenClaw | before/after tool call、message hooks、审批流程 |
| 分层安全 | 参考 OpenClaw | 路径策略 + 工具策略 + 审计日志 |
| 插件体系 | 参考 OpenClaw | pluggy/entry_points，Provider 插件化 |
| API 网关 | pkg/gateway/ | FastAPI REST API |
| 自动化测试集成 | 无（新增） | pytest + Playwright 测试报告 |

**里程碑**：生产可用，支持 RAG 知识增强，完整的安全和可观测性体系。

---

## 风险点和应对

| 风险 | 影响 | 应对方案 |
|------|------|---------|
| Browser Use 与 LangGraph 集成适配 | 中 | 参考 Browser Use 架构自研浏览器模块，不直接依赖 |
| Skills 系统 Python 无现成方案 | 低 | 参考 PicoClaw 设计，YAML 定义 + 动态加载 |
| Playwright 浏览器资源管理 | 高 | 会话池管理、超时清理、进程监控 |
| Python 生产部署（环境依赖） | 中 | Docker 容器化，固定依赖版本 |
| Playwright 镜像体积大（500MB+） | 低 | 多阶段构建，只安装需要的浏览器 |
| 动态语言长期维护 | 中 | 严格类型标注（mypy）、完善测试覆盖 |

---

## OpenClaw 对比分析与选型验证

基于对 OpenClaw（TypeScript/Node.js）源码的深入分析，验证和调整了以下技术选型：

### OpenClaw 技术栈概览

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

### Python 生态支持验证

| 调整项 | Python 支持 | 库/方案 | 风险 |
|--------|------------|--------|------|
| sqlite-vec | ✅ PyPI + LangChain 官方集成 | `sqlite-vec` + `langchain-community` | 无 |
| Playwright CDP | ✅ 原生支持 CDPSession | `browser.new_cdp_session(page)` | 无 |
| 插件体系 | ✅ 成熟模式 | `pluggy` / `importlib.entry_points` | 低 |
| 生命周期 Hook | ✅ asyncio 事件模式 | 自研，无需额外库 | 低 |
| 分层安全 | ✅ pathlib + structlog | 自研，无需额外库 | 低 |

---

## 参考资料

- [AI Agent 架构设计文档](./agent-architecture.zh.md)
- [PicoClaw vs ZeroClaw 能力对比](./agent-capability-analysis.zh.md)
- [PicoClaw 项目](../picoclaw/)
- [OpenClaw 项目](../openclaw/) - TypeScript 实现，技术选型验证参考
- [Browser Use](https://github.com/browser-use/browser-use) - 78K+ stars
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Playwright](https://playwright.dev/)
- [Playwright Python CDP](https://playwright.dev/python/docs/api/class-cdpsession)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [sqlite-vec](https://github.com/asg017/sqlite-vec) - SQLite 向量搜索扩展
- [LangChain SQLiteVec 集成](https://python.langchain.com/docs/integrations/vectorstores/sqlitevec/)
- [pluggy](https://pluggy.readthedocs.io/) - Python 插件框架
