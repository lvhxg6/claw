# Memory、Skills、Hot-reload 对比分析

## 概述

本文档对比分析 OpenClaw 和 Deer-Flow 在以下三个方面的实现：
1. 记忆系统（Memory）— MD 文档 + RAG 数据库
2. Skills 自动安装与管理
3. 配置和 Skills 文件热加载

---

## 一、记忆系统对比

### 1.1 OpenClaw 记忆系统

#### 架构概览

```
用户 Markdown 文件
    ↓
MEMORY.md / memory.md (workspace root)
memory/*.md (memory 目录下所有 md 文件)
    ↓
chunkMarkdown() 分块
    ↓
Embedding Provider (OpenAI/Gemini/Voyage/Mistral/Ollama/Local)
    ↓
SQLite + sqlite-vec 向量存储
    ↓
Hybrid Search (BM25 + Vector Similarity)
```

#### 核心文件流程

1. **Memory 文件来源**（`internal.ts`）:
   - `MEMORY.md` 或 `memory.md`（workspace 根目录，二选一）
   - `memory/` 目录下所有 `.md` 文件
   - 支持 `extraPaths` 配置额外路径

2. **Markdown 分块**（`internal.ts` - `chunkMarkdown()`）:
   ```typescript
   // 按 token 数量分块，支持 overlap 重叠
   const maxChars = Math.max(32, chunking.tokens * 4);  // 默认 tokens * 4
   const overlapChars = Math.max(0, chunking.overlap * 4);
   
   // 每个 chunk 包含：startLine, endLine, text, hash, embeddingInput
   ```

3. **向量存储**（`manager.ts`）:
   - SQLite + sqlite-vec 扩展
   - 支持多种 Embedding Provider：OpenAI、Gemini、Voyage、Mistral、Ollama、Local
   - 自动 fallback 机制（如 OpenAI 不可用则降级到 local）

4. **混合搜索**（`manager.ts` - `search()`）:
   ```typescript
   // Hybrid Search = BM25 (关键词) + Vector (语义)
   const merged = await this.mergeHybridResults({
     vector: vectorResults,
     keyword: keywordResults,
     vectorWeight: hybrid.vectorWeight,   // 默认 0.7
     textWeight: hybrid.textWeight,       // 默认 0.3
     mmr: hybrid.mmr,                     // Maximal Marginal Relevance
     temporalDecay: hybrid.temporalDecay, // 时间衰减
   });
   ```

5. **FTS-only 模式**：当没有 Embedding Provider 时，自动降级为纯 BM25 关键词搜索

#### Bootstrap Files 机制（SOUL.md、AGENTS.md 等）

OpenClaw 有一套独特的 "Bootstrap Files" 机制，用于定义 Agent 的身份和行为：

| 文件 | 用途 | 加载时机 |
|------|------|---------|
| `AGENTS.md` | Agent 工作空间规则、会话启动流程、记忆管理指南 | 每次会话启动 |
| `SOUL.md` | Agent 人格、核心价值观、行为边界 | 每次会话启动 |
| `IDENTITY.md` | Agent 身份信息（名字、emoji、头像） | 每次会话启动 |
| `USER.md` | 用户信息（名字、时区、偏好） | 每次会话启动 |
| `TOOLS.md` | 工具使用说明和本地配置 | 每次会话启动 |
| `HEARTBEAT.md` | 心跳检查任务清单 | 心跳模式 |
| `BOOTSTRAP.md` | 首次运行引导（完成后删除） | 仅首次 |
| `MEMORY.md` | 长期记忆（仅主会话加载） | 主会话 |

**实现原理**（`workspace.ts`）:
```typescript
// 默认 bootstrap 文件列表
export const DEFAULT_AGENTS_FILENAME = "AGENTS.md";
export const DEFAULT_SOUL_FILENAME = "SOUL.md";
export const DEFAULT_TOOLS_FILENAME = "TOOLS.md";
export const DEFAULT_IDENTITY_FILENAME = "IDENTITY.md";
export const DEFAULT_USER_FILENAME = "USER.md";
export const DEFAULT_HEARTBEAT_FILENAME = "HEARTBEAT.md";
export const DEFAULT_BOOTSTRAP_FILENAME = "BOOTSTRAP.md";
export const DEFAULT_MEMORY_FILENAME = "MEMORY.md";

// 加载流程
async function loadWorkspaceBootstrapFiles(dir: string): Promise<WorkspaceBootstrapFile[]> {
  // 1. 读取所有 bootstrap 文件
  // 2. 使用 boundary-safe 读取（防止路径穿越）
  // 3. 缓存文件内容（基于 inode/dev/size/mtime）
  // 4. 返回文件列表供 Agent 系统提示词使用
}
```

**安全特性**:
- 文件大小限制：`MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES = 2MB`
- 路径边界检查：防止读取 workspace 外的文件
- 文件缓存：基于 inode/mtime 的智能缓存，避免重复读取

---

### 1.2 Deer-Flow 记忆系统

#### 架构概览

```
对话消息
    ↓
MemoryUpdater.update_memory()
    ↓
LLM 提取事实和摘要
    ↓
JSON 文件存储 (memory.json)
```

#### 核心数据结构（`updater.py`）

```python
{
  "version": "1.0",
  "lastUpdated": "2024-01-01T00:00:00Z",
  "user": {
    "workContext": {"summary": "", "updatedAt": ""},      # 工作上下文
    "personalContext": {"summary": "", "updatedAt": ""},  # 个人上下文
    "topOfMind": {"summary": "", "updatedAt": ""}         # 当前关注
  },
  "history": {
    "recentMonths": {"summary": "", "updatedAt": ""},     # 近几个月
    "earlierContext": {"summary": "", "updatedAt": ""},   # 更早的上下文
    "longTermBackground": {"summary": "", "updatedAt": ""} # 长期背景
  },
  "facts": [
    {
      "id": "fact_xxx",
      "content": "用户喜欢 Python",
      "category": "preference",
      "confidence": 0.85,
      "createdAt": "2024-01-01T00:00:00Z",
      "source": "thread_123"
    }
  ]
}
```

#### 核心流程

1. **LLM 驱动的记忆更新**:
   ```python
   class MemoryUpdater:
       def update_memory(self, messages, thread_id, agent_name):
           # 1. 获取当前记忆
           current_memory = get_memory_data(agent_name)
           
           # 2. 格式化对话
           conversation_text = format_conversation_for_update(messages)
           
           # 3. 调用 LLM 提取更新
           prompt = MEMORY_UPDATE_PROMPT.format(
               current_memory=json.dumps(current_memory),
               conversation=conversation_text
           )
           response = model.invoke(prompt)
           
           # 4. 应用更新
           updated_memory = self._apply_updates(current_memory, update_data)
           
           # 5. 保存
           _save_memory_to_file(updated_memory, agent_name)
   ```

2. **事实管理**:
   - 置信度阈值过滤（`fact_confidence_threshold`）
   - 最大事实数量限制（`max_facts`）
   - 按置信度排序保留
   - 去重（基于内容）

3. **文件上传过滤**:
   ```python
   # 自动移除文件上传相关的记忆（因为文件是会话级的）
   _UPLOAD_SENTENCE_RE = re.compile(r"upload(?:ed|ing)?.*file|/mnt/user-data/uploads/")
   ```

---

### 1.3 记忆系统对比总结

| 维度 | OpenClaw | Deer-Flow |
|------|----------|-----------|
| **存储格式** | Markdown 文件 + SQLite 向量库 | JSON 文件 |
| **记忆来源** | 用户手写 MD 文件 | LLM 自动提取 |
| **检索方式** | Hybrid Search (BM25 + Vector) | 全量加载到 prompt |
| **分层设计** | Bootstrap Files (SOUL/AGENTS/USER/IDENTITY) | user/history/facts 三层 |
| **向量支持** | ✅ sqlite-vec + 多 Provider | ❌ 无 |
| **事实管理** | ❌ 无结构化事实 | ✅ 置信度 + 分类 |
| **自动更新** | ❌ 需用户手动维护 | ✅ LLM 自动提取 |
| **热加载** | ✅ chokidar 文件监听 | ✅ mtime 缓存失效 |
| **多模态** | ✅ 支持图片/音频 embedding | ❌ 仅文本 |

---

## 二、Skills 系统对比

### 2.1 OpenClaw Skills 系统

#### 目录结构

```
~/.openclaw/workspace/skills/     # 用户级
<workspace>/skills/               # 工作空间级
<workspace>/.agents/skills/       # 兼容旧版
~/.agents/skills/                 # 全局级
<plugin>/skills/                  # 插件提供
```

#### SKILL.md 格式

```markdown
---
name: web-search
description: Search the web using Tavily
tools:
  - name: tavily_search
    description: Search the web
    parameters:
      query:
        type: string
        required: true
---

# Web Search Skill

This skill provides web search capabilities...
```

#### 热加载机制（`refresh.ts`）

```typescript
// 使用 chokidar 监听 SKILL.md 文件变化
const watcher = chokidar.watch(watchTargets, {
  ignoreInitial: true,
  awaitWriteFinish: {
    stabilityThreshold: debounceMs,  // 默认 250ms
    pollInterval: 100,
  },
  ignored: DEFAULT_SKILLS_WATCH_IGNORED,  // 忽略 .git, node_modules 等
});

// 监听事件
watcher.on("add", (p) => schedule(p));
watcher.on("change", (p) => schedule(p));
watcher.on("unlink", (p) => schedule(p));

// 防抖处理
const schedule = (changedPath?: string) => {
  if (state.timer) clearTimeout(state.timer);
  state.timer = setTimeout(() => {
    bumpSkillsSnapshotVersion({ workspaceDir, reason: "watch", changedPath });
  }, debounceMs);
};
```

#### 版本管理

```typescript
// 全局版本号 + 工作空间版本号
let globalVersion = 0;
const workspaceVersions = new Map<string, number>();

// 版本号基于时间戳，保证单调递增
function bumpVersion(current: number): number {
  const now = Date.now();
  return now <= current ? current + 1 : now;
}
```

---

### 2.2 Deer-Flow Skills 系统

Deer-Flow 的 Skills 系统相对简单，主要特点：

1. **SKILL.md 格式**：与 OpenClaw 类似的 Markdown + YAML frontmatter
2. **目录结构**：`skills/` 目录下按技能名组织
3. **无热加载**：需要手动调用 reload API

---

### 2.3 Skills 系统对比总结

| 维度 | OpenClaw | Deer-Flow |
|------|----------|-----------|
| **格式** | SKILL.md (YAML frontmatter) | SKILL.md (YAML frontmatter) |
| **目录层级** | workspace/global/plugin 多级 | 单级 |
| **热加载** | ✅ chokidar 文件监听 | ❌ 手动 reload |
| **版本管理** | ✅ 时间戳版本号 | ❌ 无 |
| **防抖** | ✅ 250ms 默认 | N/A |
| **忽略规则** | ✅ .git/node_modules 等 | N/A |

---

## 三、SmartClaw 优化建议

基于以上分析，为 SmartClaw 提出以下优化方案：

### 3.1 记忆系统增强

**方案 A：OpenClaw 风格（推荐）**

```
优点：
- 用户可控，透明度高
- 支持向量检索，大规模记忆
- Bootstrap Files 机制优雅

缺点：
- 需要用户手动维护
- 学习成本较高
```

**方案 B：Deer-Flow 风格**
```
优点：
- 全自动，零维护
- 结构化事实管理
- 置信度评分

缺点：
- LLM 调用成本
- 可能提取错误信息
- 不支持大规模检索
```

**推荐方案：混合模式**
1. 支持 `MEMORY.md` 手写长期记忆（OpenClaw 风格）
2. 支持 `memory/` 目录下的 MD 文件自动索引
3. 增加 LLM 自动事实提取（Deer-Flow 风格，可选）
4. 使用 sqlite-vec 进行向量检索
5. 实现 Bootstrap Files 机制（SOUL.md、USER.md 等）

### 3.2 Skills 热加载

**推荐方案**：
1. 使用 `watchdog` 库（Python 版 chokidar）监听文件变化
2. 实现防抖机制（250ms）
3. 版本号管理（时间戳）
4. 忽略 `.git`、`__pycache__`、`venv` 等目录

```python
# 伪代码示例
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SkillsWatcher(FileSystemEventHandler):
    def __init__(self, debounce_ms=250):
        self.debounce_ms = debounce_ms
        self.timer = None
        
    def on_modified(self, event):
        if event.src_path.endswith("SKILL.md"):
            self._schedule_reload(event.src_path)
    
    def _schedule_reload(self, path):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(
            self.debounce_ms / 1000,
            lambda: bump_skills_version(path)
        )
        self.timer.start()
```

### 3.3 Bootstrap Files 机制

**推荐实现**：

| 文件 | 用途 | SmartClaw 实现 |
|------|------|---------------|
| `SOUL.md` | Agent 人格定义 | 加载到 system prompt |
| `USER.md` | 用户信息 | 加载到 system prompt |
| `MEMORY.md` | 长期记忆 | 向量索引 + 检索注入 |
| `TOOLS.md` | 工具配置说明 | 加载到 system prompt |

---

## 四、实现优先级

| 优先级 | 功能 | 复杂度 | 价值 |
|--------|------|--------|------|
| P0 | Skills 热加载（watchdog） | 低 | 高 |
| P0 | MEMORY.md 支持 | 低 | 高 |
| P1 | Bootstrap Files (SOUL/USER) | 中 | 高 |
| P1 | memory/ 目录自动索引 | 中 | 中 |
| P2 | sqlite-vec 向量检索 | 高 | 高 |
| P2 | LLM 自动事实提取 | 中 | 中 |
| P3 | Hybrid Search (BM25 + Vector) | 高 | 中 |

---

## 五、参考实现

### OpenClaw 核心文件

| 文件 | 功能 |
|------|------|
| `src/memory/internal.ts` | Memory 文件列表、分块、哈希 |
| `src/memory/manager.ts` | MemoryIndexManager，向量检索 |
| `src/memory/hybrid.ts` | Hybrid Search 实现 |
| `src/agents/workspace.ts` | Bootstrap Files 加载 |
| `src/agents/skills/refresh.ts` | Skills 热加载 |
| `docs/reference/templates/*.md` | Bootstrap 模板 |

### Deer-Flow 核心文件

| 文件 | 功能 |
|------|------|
| `agents/memory/updater.py` | LLM 驱动的记忆更新 |
| `agents/memory/prompt.py` | 记忆更新 Prompt |
| `config/memory_config.py` | 记忆配置 |
