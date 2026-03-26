# SmartClaw

工程生产级 AI Agent — 浏览器自动化、Web 调研、RPA。

## 特性

P0 核心工具（已完成）
- 8 个系统工具：文件读写/编辑/追加、目录列表、Shell 命令、Web 搜索、Web 抓取
- 15 个浏览器工具：导航、点击、输入、截图、A11y 快照、Tab 管理等
- MCP 协议：stdio + Streamable HTTP 传输，动态工具桥接
- LLM Fallback Chain：多 Provider 自动切换，指数退避 Cooldown
- 安全：路径白名单/黑名单策略，Shell 命令 deny patterns

P1 增强能力（已完成）
- 跨会话记忆：SQLite 持久化，完整消息类型支持
- 自动摘要：LLM 驱动，双阈值触发（消息数 + token 百分比）
- Skills 技能系统：YAML + SKILL.md 双格式，scripts/ 自动发现
- Native Commands：shell/script/exec 三种命令工具类型
- Sub-Agent：LangGraph SubGraph，并发控制，深度限制
- Multi-Agent：Supervisor 模式协同

## 环境要求

- Python 3.12+
- uv 包管理器 (https://docs.astral.sh/uv/)

## 快速开始

```bash
# 安装依赖
make install

# 配置环境变量
cp .env.example .env
# 编辑 .env，设置 KIMI_API_KEY（或其他 LLM API Key）

# 启动 CLI（所有特性默认开启）
uv run python -m smartclaw.cli
```

## CLI 使用

```bash
# 零配置启动，所有特性自动开启
python -m smartclaw.cli

# 指定会话名（默认自动生成）
python -m smartclaw.cli --session my-project

# 按需关闭特性
python -m smartclaw.cli --no-memory      # 关闭记忆
python -m smartclaw.cli --no-skills      # 关闭技能
python -m smartclaw.cli --no-sub-agent   # 关闭子代理
```

CLI 内置斜杠命令：

| 命令 | 说明 |
|------|------|
| /history | 查看对话历史 |
| /summary | 查看对话摘要 |
| /clear | 清空当前会话 |
| /tools | 列出所有可用工具 |
| /help | 帮助信息 |
| /quit | 退出 |

## 配置

配置文件：`config/config.yaml`

```yaml
model:
  primary: "kimi/kimi-k2.5"
  fallbacks: []
  temperature: 0.7
  max_tokens: 32768

memory:
  enabled: true
  db_path: "~/.smartclaw/memory.db"
  summary_threshold: 20

skills:
  enabled: true
  global_dir: "~/.smartclaw/skills"

sub_agent:
  enabled: true
  max_depth: 3
  max_concurrent: 5
```

环境变量覆盖（Pydantic Settings）：
```bash
SMARTCLAW_MEMORY__ENABLED=false
SMARTCLAW_MEMORY__DB_PATH=/tmp/custom.db
SMARTCLAW_SUB_AGENT__MAX_DEPTH=5
```

## Skills 技能系统

Skills 支持三种格式：

1. YAML 格式（skill.yaml）— Python 函数工具
2. SKILL.md 格式 — Markdown 提示词技能（类似 Claude Code / OpenClaw）
3. Native Command — shell/script/exec 命令工具

技能目录优先级：workspace > global > builtin

### 创建一个 SKILL.md 技能

```
~/.smartclaw/skills/my-skill/
  SKILL.md          # 技能定义（YAML frontmatter + Markdown body）
  scripts/          # 可选：自动发现的脚本
    check.sh
    analyze.py
```

SKILL.md 示例：
```markdown
---
name: system-info
description: System information gathering
tools:
  - name: sysinfo
    description: Get system information
    type: shell
    command: "bash"
    args: ["{skill_dir}/scripts/sysinfo.sh"]
---

# System Info Skill

This skill gathers system information including CPU, memory, and OS details.
```

## 项目结构

```
smartclaw/
  smartclaw/
    agent/          # Agent 编排（LangGraph StateGraph）
      graph.py      # 主图构建 + invoke
      nodes.py      # 推理/行动节点
      state.py      # AgentState 定义
      sub_agent.py  # Sub-Agent 编排
      multi_agent.py # Multi-Agent 协同
    browser/        # 浏览器引擎（Playwright + CDP）
    tools/          # 工具系统（8 个系统工具 + 浏览器工具）
    providers/      # LLM 接入（Factory + FallbackChain）
    mcp/            # MCP 协议管理器
    memory/         # 记忆系统（SQLite + AutoSummarizer）
    skills/         # Skills 技能系统
    config/         # 配置管理（Pydantic Settings + YAML）
    security/       # 安全（路径策略）
    observability/  # 日志（structlog）
    cli.py          # CLI 入口
  config/           # YAML 配置文件
  tests/            # 测试套件（638+ 测试）
```

## 测试

```bash
# 运行全部单元测试
make test

# 运行 E2E 测试（需要 API Key）
python -m pytest tests/ -m e2e --run-e2e

# 运行 CLI 场景测试
python test_cli_scenarios.py

# 运行全功能集成测试（15 个 turn，覆盖所有特性）
python test_full_integration.py
```

## 开发

```bash
make install     # 安装依赖
make lint        # 代码检查
make format      # 代码格式化
make typecheck   # 类型检查
make test        # 运行测试
```

## 技术选型

| 模块 | 选型 |
|------|------|
| Agent 编排 | LangGraph StateGraph |
| LLM 接入 | LangChain ChatModel |
| 默认模型 | Kimi 2.5（多模态） |
| 浏览器引擎 | Playwright + CDP |
| 页面理解 | Accessibility Tree |
| MCP 协议 | 官方 mcp Python SDK |
| 记忆存储 | SQLite (aiosqlite) |
| 配置 | YAML + Pydantic Settings |
| 日志 | structlog |
| HTTP | httpx |
| 包管理 | uv |
| 测试 | pytest + hypothesis |

## License

MIT
