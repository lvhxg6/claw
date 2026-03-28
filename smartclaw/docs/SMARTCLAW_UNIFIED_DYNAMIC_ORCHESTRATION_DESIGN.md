# SmartClaw 通用动态编排框架统一设计

## 1. 文档定位

这是一份单文档版总设计，用来替代前面分散的多份框架文档，作为 SmartClaw 后续动态编排框架的主入口与主设计。

本文档目标只有一个：

> 把 SmartClaw 做成一个通用超级智能体框架，后续新增业务时尽量不改核心代码，主要通过 `tools / skills / mcp / capability pack / 少量配置` 扩展。

本文档不追求一次性设计到最复杂形态，而是采用 **MVP 优先、渐进增强** 的路线。

---

## 2. 设计目标

SmartClaw 后续需要同时支持多类场景，例如：

- 开发场景：需求分析、表结构设计、API 设计、后端生成、文档生成
- 安全治理场景：基线检查、弱口令检查、漏洞检查、汇总、加固、验证、报告
- 运维场景：巡检、诊断、修复、复核

因此框架必须满足：

1. 支持动态规划，不写死流程
2. 支持 subagent 并行执行
3. 支持上一步输出稳定成为下一步输入
4. 支持 capability pack 对业务域做边界约束
5. 后续扩展主要靠配置与能力注册，不靠频繁改核心代码

---

## 3. 不采用的两种极端路线

### 3.1 不采用固定 Workflow 引擎

原因：

- 会把流程写死
- 场景一多就僵化
- 又回到“每个业务一条专用流程”的老路

### 3.2 不采用完全自由规划

原因：

- 不稳定
- 难审计
- 上下游输入输出容易漂
- 很难沉淀成通用业务框架

---

## 4. 最终方案

SmartClaw 采用：

## 动态规划 + 配置驱动约束

核心思想是：

- planner 动态决定“做什么”
- orchestrator 负责“怎么执行”
- capability pack 负责“在哪些边界内做”
- artifact 负责“如何把结果稳定传给后续步骤”

---

## 5. Phase 1 最小框架

Phase 1 只保留 5 个核心层，避免过度设计。

### 5.1 能力层：Tools / Skills / MCP

这是最底层的原子能力层。

例如：

- 安全类：基线检查、弱口令检查、漏洞扫描、加固
- 开发类：API 设计、代码生成、文档生成
- 运维类：巡检、日志分析、故障诊断

这一层后续会持续扩展，这是正常的。

### 5.2 Capability Pack

这是业务域边界层。

它只负责：

- 限定当前场景允许用哪些能力
- 定义默认模式和治理规则
- 指定审批、重试、并发边界

它不负责写死流程顺序。

例如：

- `security-pack`
- `development-pack`
- `ops-pack`

### 5.3 Planner

这是动态规划层。

它负责：

- 理解用户目标
- 判断需要哪些步骤
- 判断哪些步骤能并行
- 判断是否要补前置步骤
- 判断是否回退、重试、终止

Planner 只负责“决定做什么”，不直接执行。

### 5.4 Orchestrator

这是执行调度层。

它负责：

- 接收 planner 生成的任务列表
- 分派给 subagent / skill / tool
- 收集结果
- 将结果回传给 planner 进入下一轮规划

Orchestrator 只负责“怎么跑”，不负责业务目标理解。

### 5.5 Artifact

这是结果总线。

它负责：

- 把上一步结果沉淀下来
- 让下一步能稳定获取输入
- 避免结果只存在聊天文本里

Phase 1 采用轻量方案：

- State 中只存 `ArtifactRef`
- 实际内容存文件

而不是一开始做很重的 artifact 平台。

---

## 6. 总体架构图

```mermaid
flowchart LR
    U[User Request] --> CP[Capability Pack Resolver]
    CP --> P[Planner]
    P --> O[Orchestrator]
    O --> SA[Subagents]
    O --> TS[Tools / Skills / MCP]
    SA --> O
    TS --> O
    O --> AB[Artifact Builder]
    AB --> AS[Artifact Store]
    AS --> P
```

---

## 7. 核心职责边界

### 7.1 Planner

职责：

- 识别目标
- 决定下一轮执行哪些步骤
- 决定依赖关系和并行关系
- 决定是否继续、回退、结束

不负责：

- 真正执行 tool/skill
- 管理线程或 subagent 生命周期细节

### 7.2 Orchestrator

职责：

- 执行 planner 产出的待办任务
- 调度 subagent
- 控制并发和重试
- 收集原始结果
- 触发 artifact 生成

不负责：

- 主动推导业务目标
- 长篇推理下一步业务意图

### 7.3 Capability Pack

职责：

- 定义业务域边界
- 限定可用 steps / skills / tools
- 指定审批、重试、并发策略

不负责：

- 写死全流程

### 7.4 Artifact

职责：

- 沉淀结构化结果
- 供后续步骤消费
- 支撑 planner 稳定复用上下文

---

## 8. 简化版 Step Registry

Step Registry 在 Phase 1 不做复杂配置，只保留最小字段。

建议结构：

```yaml
id: baseline_check
domain: security
description: 对目标资产执行基线检查
inputs: [asset_scope]
outputs: [baseline_report]
preferred_skill: baseline-check-skill
can_parallel: true
risk_level: low
```

说明：

- 不引入复杂的 `applicable_when`
- 不引入复杂的 `next_step_hints`
- 不把 step 做成 mini workflow engine

step 只是 planner 的“可选步骤目录”。

---

## 9. Step Registry 的作用

Step Registry 的唯一目的，是告诉 planner：

- 有哪些步骤可选
- 每个步骤大概做什么
- 每个步骤吃什么输入
- 每个步骤产出什么输出
- 推荐调用哪个 skill

Planner 仍然动态决定：

- 是否要选它
- 何时选它
- 是否并行
- 是否跳过

---

## 10. Capability Pack 的最小职责

Pack 在 Phase 1 只做四类约束：

1. **允许什么**
   - 允许哪些 tools / skills / steps

2. **禁止什么**
   - 禁止哪些高风险步骤或能力

3. **治理什么**
   - 哪些步骤要审批
   - 最大并发多少
   - 最多重试几次

4. **偏好什么**
   - 默认偏向 orchestrator
   - 默认优先选择哪些步骤类型

Pack 不写死流程图。

---

## 11. Artifact 的轻量实现

Phase 1 不做重量级 artifact 模型，只做两层。

### 11.1 State 中的轻量引用

```yaml
id: art_001
type: baseline_report
producer_step: baseline_check
status: ready
path: /artifacts/art_001.json
```

### 11.2 文件中的实际内容

```json
{
  "summary": "主机基线检查完成，发现 3 项不符合",
  "data": {
    "findings": [...]
  },
  "metadata": {
    "asset_scope": "..."
  }
}
```

这样做的好处：

- State 保持轻量
- planner 能快速引用
- 复杂内容不挤进内存状态
- 后续再升级也容易

### 11.3 与 Session 的关系

Phase 1 建议 artifact 按 session 隔离存储。

建议路径形式：

```text
sessions/{session_id}/artifacts/{artifact_id}.json
```

这样做的目的：

- 不同会话之间天然隔离
- 便于回放、归档、清理
- 后续如果要做项目级聚合，也更容易在 session 之上再做抽象

建议策略：

- 会话运行期间：artifact 保留在当前 session 目录中
- 会话结束后：可按策略选择归档或清理
- 需要长期保留的关键产物：后续再提升到项目级或知识库级存储

---

## 12. Middleware 机制

Phase 1 建议增加 3 个 Middleware，不做更多。

### 12.1 artifact_middleware

负责：

- 把执行结果标准化为 artifact
- 存储 artifact 引用

### 12.2 governance_middleware

负责：

- 审批检查
- 并发限制
- 重试限制
- 风险边界检查

### 12.3 step_tracking_middleware

负责：

- 记录 step 状态
- 记录 subagent 执行状态
- 记录失败和重试轨迹

这样横切逻辑不会堆进 orchestrator 主循环。

---

## 13. Skill 渐进式加载

Phase 1 必须支持按需加载 skill，而不是全量注入 prompt。

原因：

- 后续业务场景多，skill 很多
- 如果全部注入，上下文窗口会爆
- planner 和 step 只需要当前步骤相关能力

建议逻辑：

- planner 选出 step
- step 指向 `preferred_skill`
- skill loader 只加载当前步骤需要的 skill 内容

这样更接近 deer-flow 的轻量运行方式。

---

## 14. 典型运行流程

```mermaid
flowchart TD
    A[User Goal] --> B[Resolve Capability Pack]
    B --> C[Load Candidate Steps]
    C --> D[Planner 生成待办任务]
    D --> E[Orchestrator 执行任务]
    E --> F[Subagent / Skill / Tool 执行]
    F --> G[Artifact 生成]
    G --> H[Planner 重新规划]
    H --> I{是否结束}
    I -->|否| E
    I -->|是| J[最终汇总输出]
```

---

## 15. 安全治理场景示例

用户输入：

> 跑基线、弱口令、漏洞检查，并根据结果动态加固

系统执行方式：

1. 识别为 `security-pack`
2. 只开放安全相关步骤
3. planner 判断：
   - `baseline_check`
   - `weak_password_check`
   - `vulnerability_scan`
   可以并行
4. orchestrator 分派三个 subagent
5. 三个检查结果沉淀为 artifact
6. planner 判断是否需要 `hardening`
7. 如需要，执行加固，再执行 `verification`
8. 生成最终报告

关键点：

- 没有写死流程脚本
- 但也不是完全自由乱跑
- 动态规划建立在 pack 边界和 artifact 结果之上

---

## 16. 开发场景示例

用户输入：

> 根据需求生成 API 设计和接口文档

系统执行方式：

1. 识别为 `development-pack`
2. 开放开发相关步骤
3. planner 判断：
   - 如果没有结构化需求，先做 `requirement_analysis`
   - 然后做 `api_design`
   - 最后做 `api_doc_generate`
4. artifact 依次沉淀：
   - `requirement_summary`
   - `api_contract`
   - `api_doc`

这里依然不是固定 workflow。

---

## 17. Phase 1 不做的东西

为了避免过度设计，以下内容明确延期到后续：

- 很复杂的 artifact schema 体系
- 很复杂的 planner scoring 体系
- 很复杂的 step 条件配置
- 很复杂的 workflow 模板系统
- 很复杂的 sandbox 设计
- 很复杂的运行时状态树

这些不是现在第一阶段的必须项。

---

## 18. 后续扩展方式

当框架搭起来之后，后续新增业务应该主要通过下面方式扩展。

### 18.1 新增原子能力

新增：

- tool
- skill
- mcp

### 18.2 新增业务边界

新增：

- capability pack

### 18.3 新增可复用步骤

新增：

- step definition

理想情况下，不需要改：

- planner 主体
- orchestrator 主体
- gateway 主体

只有新增“通用调度机制”时，才应该修改核心代码。

---

## 19. Phase 1 最小实现清单

建议第一阶段只做：

1. 最小 `Capability Pack` 运行机制
2. 最小 `Step Registry`
3. `Planner` 与 `Orchestrator` 职责切分
4. 轻量 `ArtifactRef + 文件存储`
5. 三个 middleware：
   - `artifact_middleware`
   - `governance_middleware`
   - `step_tracking_middleware`
6. Skill 按需加载
7. 一个试点场景打通

---

## 20. 现有代码映射与过渡方案

为了避免该设计停留在目标架构层，下面明确当前 SmartClaw 代码与目标框架之间的映射关系。

### 20.1 当前代码与目标层的对应关系

| 目标层 | 当前代码 | 结论 |
| --- | --- | --- |
| Planner | [plan_manager.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/plan_manager.py) | 当前是关键词匹配型粗规划器，需要升级 |
| Orchestrator | [orchestrator_graph.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/orchestrator_graph.py)、`dispatch_tasks.py`、`dispatch_policy.py` | 大体可复用 |
| Capability Pack | `smartclaw/capabilities/` | 已有基础，需要补 `allowed_steps / preferred_steps` |
| Artifact | 无正式层 | 需要新增轻量 `ArtifactRef + file` |
| Middleware | 治理逻辑散在 [governance.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/capabilities/governance.py) 与 graph 节点里 | 需要抽成统一机制 |
| Runtime State | `AgentState`、`task_results`、`todos` | 已有部分骨架，可逐步增强 |

### 20.2 最关键的现实问题

当前 [plan_manager.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/plan_manager.py) 中的 `_infer_todos()` 仍然是基于关键词的硬编码逻辑。

这意味着：

- 现在的 planner 不是通用动态规划器
- 它更像一个规则型粗分类器
- 因此 Phase 1 需要明确过渡路径，而不是直接假设系统已经具备 LLM 级别动态规划能力

### 20.3 过渡路径

建议分三步走：

#### Phase 1A：保留 Rule Planner 作为 fallback

- 继续保留当前 `PlanManager` 的关键词规划能力
- 作为保底路径存在

#### Phase 1B：新增 LLM Planner

- 新增一个真正的 `LLMPlanner`
- 它基于：
  - capability pack
  - 最小 step registry
  - 当前 artifacts
  - 用户目标
  生成结构化 todos

#### Phase 1C：Rule Planner 退为兜底

- 主路径改为 `LLMPlanner`
- `RulePlanner` 只在以下情况触发：
  - 模型不可用
  - planner 输出不合法
  - pack 禁止当前自由规划

这里“输出不合法”应明确为：

- LLM 输出无法解析为 JSON
- JSON schema 校验失败
- 缺少必填字段，例如：
  - `todos`
  - `todo.id`
  - `todo.depends_on`

满足上述任一条件时，应自动降级到 `RulePlanner`，而不是直接让 orchestrator 消费不稳定结果。

---

## 21. Planner 设计与 Prompt 结构

Step Registry 简化后，更多智能必须进入 planner prompt。

### 21.1 Planner 输入

Planner 至少应看到：

- 当前用户目标
- active capability pack
- 候选 step 列表
- 当前 ready artifacts 摘要
- 当前已完成 / 失败 / 等待审批的步骤状态

### 21.2 Step 注入格式

不应把 step 全量配置塞给模型，而应以简化摘要形式注入：

```yaml
- id: "baseline_check"
  description: "对目标资产执行基线检查"
  inputs: ["asset_scope"]
  outputs: ["baseline_report"]
  can_parallel: true
  risk_level: "low"
```

### 21.3 Planner 输出格式

建议 planner 输出最小结构化结果：

```json
{
  "objective": "执行安全治理闭环",
  "todos": [
    {
      "id": "baseline_check",
      "title": "执行基线检查",
      "inputs": ["asset_scope"],
      "depends_on": [],
      "parallelizable": true
    }
  ],
  "reasoning_summary": "先并行执行三个检查，再根据结果决定是否加固"
}
```

### 21.4 Planner 成功标准

Planner 不要求一次推理出全流程，只要求每轮稳定产出：

- 当前最合理的一组 todos
- 每个 todo 的依赖关系
- 是否还缺关键输入

---

## 22. Middleware 机制与挂载位置

这里不直接照搬 DeerFlow 的 `before_model / after_model` 挂载方式。

原因是：

- DeerFlow 更偏 agent harness
- SmartClaw 当前主线是 `graph node + runtime + gateway`

因此，SmartClaw Phase 1 的 middleware 更合理的形态是：

## graph-stage middleware

即挂在 orchestrator graph 的阶段节点之间，而不是模型调用前后。

### 22.1 建议挂载点

- `planner before / after`
- `dispatch before / after`
- `step result normalize`
- `synthesize before / after`

### 22.2 Phase 1 三个 Middleware 的落点

#### artifact_middleware

挂在：

- `execute -> review`
- `synthesize -> final`

作用：

- 将原始结果标准化为 artifact
- 建立 artifact 引用

#### governance_middleware

挂在：

- `dispatch before`
- `execute after`

作用：

- 审批检查
- 并发限制
- 重试限制
- 风险控制

#### step_tracking_middleware

挂在：

- `planner after`
- `dispatch after`
- `execute after`
- `review after`

作用：

- 记录 step / subagent 状态
- 记录失败和重试轨迹

---

## 23. 错误处理、回退与 Replanning 语义

动态编排框架必须明确失败和回退语义。

### 23.1 Step 执行失败

当某 step 执行失败时：

1. orchestrator 先按 pack 的重试策略决定是否重试
2. 若重试后仍失败，则把该 step 标记为 `failed`
3. planner 在下一轮看到失败状态后决定：
   - 改走其他步骤
   - 请求用户补输入
   - 终止流程

### 23.2 Artifact 不符合预期

当某 step 产出的结果无法形成有效 artifact 时：

1. 标记 artifact 为 `invalid` 或不生成
2. 记录失败原因
3. 触发 replanning

### 23.3 Replanning 触发条件

以下情况应触发 replanning：

- 缺少关键输入
- step 执行失败
- 关键 artifact 无效
- verification 不通过
- approval 被拒绝
- planner 判断当前路径已不适合继续

### 23.4 当前代码复用点

当前 [orchestrator_graph.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/orchestrator_graph.py) 中已经具备部分 review 语义：

- `completed`
- `ready`
- `blocked`

Phase 1 不应推翻它，而应在这套 review 机制上补充：

- artifact 状态
- retry 结果
- replanning 触发原因

---

## 24. 推荐试点场景

优先推荐：

### 24.1 安全治理场景

因为它最能验证：

- 动态规划
- 并行执行
- 条件分支
- 审批
- artifact 串联

试点链路：

- 基线检查
- 弱口令检查
- 漏洞检查
- 汇总
- 条件加固
- 验证
- 报告

### 24.2 开发场景

作为第二个试点：

- 需求分析
- API 设计
- 文档生成

---

## 25. 最终结论

SmartClaw 后续要做的，不是固定 workflow 平台，也不是完全自由的 agent。

而是：

## 一个“动态规划 + 配置驱动约束”的通用超级智能体框架

它的最小核心只有：

- Tools / Skills / MCP
- Capability Pack
- Planner
- Orchestrator
- 轻量 Artifact

在这个基础上，后续主要通过新增能力和配置扩展业务，而不是持续改核心框架代码。
