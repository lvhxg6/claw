# SmartClaw 设计优化建议

## 1. 文档目的

本文档基于对 SmartClaw 现有设计文档（7 份核心设计）和 DeerFlow 2.0 实际架构的对比分析，提出针对性的优化建议。

核心原则：**先跑通最小闭环，再逐步增强。不要一开始就设计得太复杂。**

---

## 2. 优化总览

| 维度 | 当前设计 | 问题 | 优化方向 |
|------|----------|------|----------|
| Step Registry | 字段过多（15+ 字段） | 配置地狱，落地成本高 | 简化到 5-6 个核心字段 |
| Artifact | 单层重结构 | State 膨胀，序列化开销大 | 分层：轻量引用 + 文件存储 |
| Middleware | 缺失 | 治理逻辑耦合在 Orchestrator 里 | 补充 Middleware 链机制 |
| Planner / Orchestrator | 职责混用 | 边界不清，难以独立演进 | 明确分工，拆清接口 |
| Skill 加载 | 未提及加载策略 | 全量加载会撑爆 context window | 渐进式按需加载 |
| Sandbox / 执行环境 | 未涉及 | 无法支撑代码执行和文件操作场景 | 根据场景补充 Sandbox 设计 |
| 设计索引 | 纯文档列表 | 缺少快速上手路径 | 增加快速理解和操作指引 |

---

## 3. 优化点 1：简化 Step Registry

### 3.1 当前问题

当前 `SMARTCLAW_STEP_REGISTRY_SPEC.md` 中的 Step Definition 包含过多字段：

- `applicable_when`（含 `scenario_types`、`keywords`、`task_profiles`、`packs`）
- `preconditions`
- `next_step_hints`
- `execution`（含 `preferred_skill`、`allowed_tools`、`can_run_parallel`、`risk_level`、`preferred_subagent_type`）
- `artifacts_produced`（含 `schema` 引用）
- `metadata`

这在实际落地时会变成配置地狱：每新增一个步骤，需要填写大量字段，维护成本极高。

### 3.2 DeerFlow 的做法

DeerFlow 2.0 没有显式的 Step Registry。它的做法是：

- Lead Agent 通过 `task` 工具动态分派子任务
- 子任务的定义完全由 LLM 在运行时决定
- Skills 提供能力描述，但不预定义步骤模板
- Middleware 控制并发和边界，而不是配置文件

这意味着 DeerFlow 把"步骤选择"的智能完全交给了 LLM，而不是配置系统。

### 3.3 优化建议

保留 Step Registry 的概念（因为 SmartClaw 面向的业务场景比 DeerFlow 更复杂，需要一定的约束），但大幅简化字段：

```yaml
# 简化版 Step Definition - 只保留核心字段
id: baseline_check
name: 基线检查
domain: security
description: 对目标资产执行基线检查并输出结构化发现

inputs: [asset_scope]
outputs: [baseline_report]
preferred_skill: baseline-check-skill
can_parallel: true
risk_level: low
```

**砍掉的字段和理由**：

| 砍掉的字段 | 理由 |
|------------|------|
| `applicable_when` | 交给 Planner 的 prompt 判断，LLM 比静态规则更擅长语义匹配 |
| `next_step_hints` | 交给 Planner 动态决定，写死提示反而限制灵活性 |
| `preconditions.required_user_inputs` | 合并到 `inputs` 里，不需要单独区分来源 |
| `artifacts_produced.schema` | 第一阶段不需要 schema 校验，先跑通再加 |
| `execution.preferred_subagent_type` | 第一阶段只有一种 subagent，不需要区分 |
| `metadata` | 非核心，后续按需加 |

**保留但后续可扩展的字段**：

```yaml
# Phase 2 可选扩展
preconditions: [api_contract]  # 简化为 artifact 名称列表
allowed_tools: [check_baseline, scan_host]
```

### 3.4 核心原则

> 把"哪些步骤适合当前任务"的判断交给 LLM，而不是交给配置文件。
> Step Registry 只负责告诉 LLM "有哪些步骤可选、每步吃什么吐什么"。

---

## 4. 优化点 2：Artifact 分层设计

### 4.1 当前问题

当前 `SMARTCLAW_ARTIFACT_SPEC.md` 定义的 Artifact 结构包含 16 个字段，全部存在运行时 State 中：

```yaml
artifact_id, type, domain, producer_step, status, summary,
data, schema_ref, version, supersedes, source_inputs,
source_artifacts, tags, confidence, created_at, updated_at, metadata
```

如果一个复杂任务产出 10+ 个 Artifact，每个 Artifact 的 `data` 字段可能很大（比如完整的漏洞报告），这会导致：

- State 序列化/反序列化开销大
- LangGraph checkpoint 体积膨胀
- Planner 每轮规划时需要处理大量无关数据

### 4.2 DeerFlow 的做法

DeerFlow 用极简方式处理产物：

- `ThreadState.artifacts` 只存文件路径列表（`list[str]`）
- 实际内容存在文件系统里（`/mnt/user-data/outputs/`）
- Sandbox 提供虚拟路径映射

这样 State 始终保持轻量。

### 4.3 优化建议：分两层

#### 轻量引用层（存在 State 里）

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ArtifactRef:
    """轻量 Artifact 引用，存在运行时 State 中"""
    id: str                    # 唯一标识
    type: str                  # baseline_report, api_contract...
    producer_step: str         # 产出该 artifact 的 step id
    status: str                # draft | ready | invalid
    summary: str               # 一句话摘要，供 Planner 快速判断
    path: str                  # 实际文件路径
    created_at: str            # ISO 时间戳
```

#### 完整内容层（存在文件系统里）

```
artifacts/
  art_001_baseline_report.json
  art_002_vuln_report.json
  art_003_api_contract.json
```

每个文件的结构：

```json
{
  "artifact_id": "art_001",
  "type": "baseline_report",
  "producer_step": "baseline_check",
  "summary": "已完成基线检查，发现 6 项不符合项",
  "data": {
    "findings": ["..."],
    "risk_level": "high",
    "need_hardening": true
  },
  "source_artifacts": ["art_000_asset_scope"],
  "version": 1,
  "created_at": "2026-03-28T10:00:00Z"
}
```

### 4.4 Planner 消费方式

Planner 每轮规划时只看 `ArtifactRef` 列表：

```python
# Planner 看到的是这样的轻量列表
artifacts = [
    ArtifactRef(id="art_001", type="baseline_report", status="ready",
                summary="基线检查完成，6项不符合", ...),
    ArtifactRef(id="art_002", type="vuln_report", status="ready",
                summary="发现3个高危漏洞", ...),
]
```

只有当 Step 真正需要消费某个 Artifact 时，才从文件系统读取完整内容。

### 4.5 砍掉的字段

| 砍掉的字段 | 理由 |
|------------|------|
| `confidence` | 第一阶段不需要，LLM 判断即可 |
| `supersedes` | 版本管理后续再加 |
| `schema_ref` | 先不做 schema 校验 |
| `tags` | 用 `type` + `domain` 足够检索 |
| `metadata` | 非核心 |

---

## 5. 优化点 3：补充 Middleware 机制

### 5.1 当前问题

当前设计中，治理逻辑（Pack 约束检查、审批、重试）、上下文管理（Artifact 收集、Context 压缩）、观测逻辑（执行追踪、决策记录）都没有明确的执行位置。

如果全部写在 Orchestrator 里，会导致 Orchestrator 变成一个巨大的 God Object。

### 5.2 DeerFlow 的做法

DeerFlow 的核心能力大量通过 Middleware 链实现：

```
ThreadDataMiddleware    → 初始化工作空间和路径
UploadsMiddleware       → 处理上传文件，注入文件列表
SandboxMiddleware       → 获取沙箱环境
SummarizationMiddleware → 上下文压缩（token 超限时自动摘要）
TitleMiddleware         → 自动生成会话标题
TodoListMiddleware      → 任务追踪（Plan 模式）
ViewImageMiddleware     → Vision 模型支持
ClarificationMiddleware → 处理澄清请求
```

每个 Middleware 职责单一，可独立开发、测试、替换。

### 5.3 优化建议

在 SmartClaw 中引入 Middleware 链机制：

```
smartclaw/agent/middlewares/
├── __init__.py
├── base.py                     # Middleware 基类
├── artifact_middleware.py      # Artifact 自动收集和存储
├── step_tracking_middleware.py # Step 执行状态追踪
├── governance_middleware.py    # Pack 治理规则检查（审批、工具限制）
├── context_pruning_middleware.py # 上下文压缩
├── upload_middleware.py        # 上传文件处理（已有，可迁入）
├── observability_middleware.py # 执行追踪和决策记录
```

#### Middleware 基类设计

```python
from abc import ABC, abstractmethod
from typing import Any

class Middleware(ABC):
    """Middleware 基类"""

    @abstractmethod
    async def before(self, state: dict, config: dict) -> dict:
        """在 Agent 执行前处理 state"""
        return state

    @abstractmethod
    async def after(self, state: dict, config: dict) -> dict:
        """在 Agent 执行后处理 state"""
        return state
```

#### Middleware 链执行

```python
class MiddlewareChain:
    def __init__(self, middlewares: list[Middleware]):
        self.middlewares = middlewares

    async def run_before(self, state: dict, config: dict) -> dict:
        for mw in self.middlewares:
            state = await mw.before(state, config)
        return state

    async def run_after(self, state: dict, config: dict) -> dict:
        for mw in reversed(self.middlewares):
            state = await mw.after(state, config)
        return state
```

### 5.4 各 Middleware 职责

| Middleware | before | after |
|-----------|--------|-------|
| `ArtifactMiddleware` | 加载已有 Artifact 引用到 State | 从执行结果中提取新 Artifact 并存储 |
| `StepTrackingMiddleware` | 记录 Step 开始时间和状态 | 记录 Step 结束时间、结果、耗时 |
| `GovernanceMiddleware` | 检查 Pack 约束（工具白名单、审批要求） | 检查输出是否符合 Pack 规则 |
| `ContextPruningMiddleware` | 检查 token 用量，必要时压缩历史 | 无 |
| `ObservabilityMiddleware` | 记录决策输入 | 记录决策输出和执行轨迹 |

---

## 6. 优化点 4：明确 Planner 和 Orchestrator 职责边界

### 6.1 当前问题

在现有设计文档中，Planner 和 Orchestrator 经常混用：

- `SMARTCLAW_DYNAMIC_ORCHESTRATION_FRAMEWORK.md` 中 "Planner / Orchestrator 层" 合在一起
- `SMARTCLAW_DYNAMIC_ORCHESTRATION_BLUEPRINT.md` 中 "Planner / Orchestrator" 作为一个整体出现
- `SMARTCLAW_PLANNER_INPUT_RESOLUTION_SPEC.md` 中 Planner 的职责描述包含了调度逻辑

这会导致实现时边界不清，两个组件互相侵入。

### 6.2 优化建议：明确分工

```
┌─────────────────────────────────────────────────────┐
│                     Planner                          │
│                                                      │
│  输入：用户目标 + Artifact 列表 + Pack 约束          │
│  输出：Step-aware Todos（带依赖关系）                │
│                                                      │
│  职责：                                              │
│  - 理解用户目标                                      │
│  - 识别适用的 Capability Pack                        │
│  - 从 Step Registry 选择候选步骤                     │
│  - 根据 Artifact 状态判断哪些步骤可执行              │
│  - 生成 Todos 并标注依赖关系和并行性                 │
│  - 每轮执行后根据新 Artifact 重新规划                │
│                                                      │
│  不负责：                                            │
│  - 具体的分派调度                                    │
│  - Subagent 生命周期管理                             │
│  - 并发控制                                          │
│  - 结果收集                                          │
└──────────────────────┬──────────────────────────────┘
                       │ Todos
                       ▼
┌─────────────────────────────────────────────────────┐
│                   Orchestrator                        │
│                                                      │
│  输入：Todos（来自 Planner）                         │
│  输出：Task Results + 新 Artifacts                   │
│                                                      │
│  职责：                                              │
│  - 按 Dispatch Policy 将 Todos 分 Batch             │
│  - 分派 Subagent 执行                                │
│  - 管理并发限制                                      │
│  - 收集执行结果                                      │
│  - 触发 Artifact Builder 沉淀产物                    │
│  - 判断是否需要触发下一轮 Planner                    │
│  - 最终 Synthesize 汇总                              │
│                                                      │
│  不负责：                                            │
│  - 决定做什么步骤                                    │
│  - 选择哪些步骤并行                                  │
│  - 理解用户意图                                      │
└─────────────────────────────────────────────────────┘
```

### 6.3 交互协议

```python
# Planner 输出
@dataclass
class PlannedTodo:
    todo_id: str
    step_id: str          # 对应 Step Registry 中的 id
    title: str
    depends_on: list[str] # 依赖的其他 todo_id
    parallel_group: str   # 同组可并行
    input_bindings: dict  # 输入来源映射

# Orchestrator 消费
class Orchestrator:
    async def execute_plan(self, todos: list[PlannedTodo]) -> list[TaskResult]:
        batches = self.dispatch_policy.build_batches(todos)
        for batch in batches:
            results = await self.run_batch(batch)
            # 收集结果，构建 Artifact
            ...
        return all_results
```

---

## 7. 优化点 5：Skill 渐进式加载

### 7.1 当前问题

当前设计未提及 Skill 的加载策略。如果所有 Skill 的内容都在启动时注入到 System Prompt 中，会导致：

- Context Window 快速耗尽
- 无关 Skill 内容干扰 LLM 判断
- 新增 Skill 时 prompt 越来越长

### 7.2 DeerFlow 的做法

DeerFlow 的 Skills 是渐进式加载的：

> Skills are loaded progressively — only when the task needs them, not all at once.
> This keeps the context window lean and makes DeerFlow work well even with token-sensitive models.

### 7.3 优化建议

```python
class SkillLoader:
    """渐进式 Skill 加载器"""

    def __init__(self, skill_registry, step_registry):
        self.skill_registry = skill_registry
        self.step_registry = step_registry

    def load_skill_summary(self) -> str:
        """加载所有 Skill 的摘要（用于 Planner 规划）"""
        summaries = []
        for skill in self.skill_registry.list_all():
            summaries.append(f"- {skill.name}: {skill.description}")
        return "\n".join(summaries)

    def load_skill_for_step(self, step_id: str) -> str:
        """只加载当前 Step 需要的 Skill 完整内容（用于 Subagent 执行）"""
        step = self.step_registry.get(step_id)
        if not step or not step.preferred_skill:
            return ""
        skill = self.skill_registry.get(step.preferred_skill)
        return skill.full_content if skill else ""
```

#### 加载时机

| 阶段 | 加载内容 | 目的 |
|------|----------|------|
| Planner 规划 | Skill 摘要列表 | 让 Planner 知道有哪些能力可用 |
| Subagent 执行 | 当前 Step 对应的 Skill 完整内容 | 让执行者获得详细指导 |

---

## 8. 优化点 6：Sandbox / 执行环境设计

### 8.1 当前问题

当前设计文档完全没有涉及执行环境隔离。如果 SmartClaw 要支持：

- 代码生成后的编译测试
- Shell 命令执行
- 文件读写操作
- 多任务并行执行

就需要考虑执行环境的隔离和安全。

### 8.2 DeerFlow 的做法

DeerFlow 提供三级 Sandbox：

```
Local Sandbox   → 直接在宿主机执行（开发用）
Docker Sandbox  → 每个 Thread 一个容器（生产用）
K8s Sandbox     → 通过 Provisioner 动态创建 Pod（规模化用）
```

每个 Thread 有独立的文件系统：

```
/mnt/user-data/
├── uploads/     ← 用户上传的文件
├── workspace/   ← Agent 的工作目录
└── outputs/     ← 最终产物
```

### 8.3 优化建议

SmartClaw 当前场景（安全治理、开发辅助）确实需要执行环境。建议分阶段：

#### Phase 1：Local 执行 + 路径隔离

```python
class LocalExecutionEnv:
    """本地执行环境，通过路径隔离实现基本安全"""

    def __init__(self, session_id: str):
        self.base_path = f"./sessions/{session_id}"
        self.workspace = f"{self.base_path}/workspace"
        self.artifacts_dir = f"{self.base_path}/artifacts"
        self.uploads_dir = f"{self.base_path}/uploads"

    async def execute(self, command: str, cwd: str = None) -> str:
        """在隔离路径下执行命令"""
        ...
```

#### Phase 2：Docker 隔离（按需）

如果需要执行不可信代码或高风险操作，再引入 Docker Sandbox。

---

## 9. 优化点 7：设计索引增强

### 9.1 当前问题

`SMARTCLAW_DESIGN_INDEX.md` 主要是文档列表和阅读顺序，缺少：

- 快速上手路径
- 架构一图流
- 新增业务的操作指引

### 9.2 优化建议

建议在 INDEX 中增加以下内容：

#### 快速理解（5 分钟版）

```
如果你只有 5 分钟，看这张图：
→ SMARTCLAW_DYNAMIC_ORCHESTRATION_BLUEPRINT.md 第 3 节（总体架构图）

如果你要理解核心概念：
→ Tool（原子动作）→ Skill（能力封装）→ Step（步骤模板）
→ Pack（业务域边界）→ Artifact（结构化产物）
→ Planner（动态规划）→ Orchestrator（调度执行）
```

#### 新增业务操作指引

```
新增一个业务场景的标准步骤：

1. 定义 Capability Pack（config/packs/my-pack.yaml）
   - 声明允许的 tools、skills、steps
   - 设置治理规则

2. 定义 Step Definitions（step_registry/my-domain/）
   - 每个步骤的输入输出
   - 推荐使用的 skill

3. 实现对应的 Skill / Tool
   - 如果是新能力，新增 tool
   - 如果是已有能力的业务封装，新增 skill

4. 测试
   - 单步骤测试
   - 端到端编排测试
```

---

## 10. 实施优先级建议

基于以上优化点，建议的实施优先级：

### 第一优先级（框架基础）

1. **简化 Step Registry** — 用简化版 schema 先跑通
2. **Artifact 分层** — 轻量引用 + 文件存储
3. **明确 Planner / Orchestrator 分工** — 拆清接口

### 第二优先级（工程质量）

4. **Middleware 机制** — 解耦治理、观测、上下文管理
5. **Skill 渐进式加载** — 控制 context window

### 第三优先级（能力增强）

6. **Sandbox 设计** — 根据实际场景决定
7. **设计索引增强** — 提升团队协作效率

---

## 11. 与 DeerFlow 的关键差异定位

最后明确一下 SmartClaw 和 DeerFlow 的定位差异，避免盲目对齐：

| 维度 | DeerFlow 2.0 | SmartClaw |
|------|-------------|-----------|
| 定位 | 通用 Super Agent Harness | 面向企业多业务域的动态编排框架 |
| 步骤管理 | 无显式 Step Registry，完全靠 LLM | 有 Step Registry，LLM + 配置约束 |
| 业务域治理 | 无 Capability Pack | 有 Capability Pack，支持审批/限制 |
| 产物管理 | 文件路径列表 | 结构化 Artifact（分层） |
| 执行环境 | Docker/K8s Sandbox | 先 Local，按需 Docker |
| 扩展方式 | Skills + MCP | Skills + MCP + Step + Pack |
| 前端 | Next.js 完整 UI | Gateway API 优先 |

SmartClaw 比 DeerFlow 多了一层"业务域治理"，这是企业场景的刚需。但也因此需要更注意不要过度设计，保持配置的简洁性。

---

## 12. 结论

当前设计的大方向是正确的。核心优化点是：

1. **做减法** — Step Registry 和 Artifact 都需要简化，先跑通最小闭环
2. **补 Middleware** — 把散落的横切关注点收拢到 Middleware 链里
3. **拆清边界** — Planner 只管规划，Orchestrator 只管调度
4. **渐进加载** — Skill 按需加载，控制 context window
5. **分层存储** — Artifact 引用和内容分离，State 保持轻量

一句话：**设计够用就好，先让框架跑起来，再在实践中迭代。**
