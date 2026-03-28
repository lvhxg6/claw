# SmartClaw 通用动态编排框架设计

## 1. 文档目标

本文档定义 `smartclaw` 面向多业务域的通用动态编排框架设计。

目标不是为某一个固定场景写死流程，而是把 `smartclaw` 做成一个可扩展的超级智能体框架，使后续新增业务时，尽量通过新增：

- `tools`
- `skills`
- `mcp`
- `capability pack`
- `step definitions`

来扩展，而不是持续修改核心编排代码。

本文档结合当前 `smartclaw` 的已实现能力，以及对 `deer-flow` 的实现调研结果，给出推荐的目标架构。

---

## 2. 核心结论

### 2.1 最终方向

`smartclaw` 不应走“固定 workflow 引擎”路线，而应走：

**动态规划 + 受控分派 + 配置驱动扩展**

也就是：

- 主 agent 负责动态规划
- orchestrator 负责分阶段调度与 subagent 分派
- 规则边界通过配置约束
- 业务扩展主要靠能力注册和步骤定义

### 2.2 不推荐的路线

不推荐：

- 先做多个固定业务页面
- 再把这些页面逻辑硬嵌到 `smartclaw`
- 或者把每个业务都写成固定顺序的 workflow 脚本

原因：

- 会继续保留业务割裂
- 流程关系仍然在业务页面系统里，不在智能体里
- 扩展新业务仍然需要改核心逻辑

### 2.3 推荐的路线

推荐：

- 把 `smartclaw` 建成一个通用动态编排框架
- 让不同业务场景通过“能力 + 规则 + 步骤定义”接入
- 由 planner 动态决定要做哪些步骤、顺序如何、是否并行、是否跳过、是否回退

---

## 3. 当前 SmartClaw 已有基础

当前 `smartclaw` 已经具备构建通用动态编排框架的大部分基础能力。

### 3.1 双模式运行时

当前已有：

- `classic`
- `orchestrator`
- `auto`

相关实现：

- `smartclaw/agent/mode_router.py`
- `smartclaw/agent/orchestrator_graph.py`

说明：

- 已经有动态模式分流
- 已经不是单纯的 classic ReAct agent

### 3.2 Orchestrator 骨架

当前 orchestrator 已有：

- 计划生成
- todo 列表
- batch 构建
- phase 级推进
- synthesize 汇总

相关实现：

- `smartclaw/agent/orchestrator_graph.py`
- `smartclaw/agent/plan_manager.py`
- `smartclaw/agent/dispatch_policy.py`

### 3.3 Subagent 分派运行时

当前已有：

- `spawn_sub_agent`
- 受控批次分派
- 并发限制
- task retry
- 结果汇总

相关实现：

- `smartclaw/agent/dispatch_tasks.py`
- `smartclaw/agent/sub_agent.py`

### 3.4 Capability Pack 基础设施

当前已有：

- pack manifest
- tool policy
- schema enforcement
- approval
- pack-level retry / concurrency governance

相关实现：

- `smartclaw/capabilities/models.py`
- `smartclaw/capabilities/registry.py`
- `smartclaw/capabilities/governance.py`

### 3.5 附件 / 上下文 / 观测能力

当前已有：

- 文档上传与分析
- 图片 OCR / vision route
- 统一上下文拼装
- hooks / decisions / execution 观测

说明：

这意味着 `smartclaw` 已经不缺“单点能力”，缺的是更通用的编排抽象。

---

## 4. DeerFlow 调研结论

对 `deer-flow` 的调研结论如下。

### 4.1 deer-flow 不是固定 workflow 引擎

`deer-flow` 的核心不是预先写死流程，而是：

- `lead agent` 动态规划
- `task` 工具触发 subagent
- middleware 控制并发和边界
- `todos` / `artifacts` 作为轻量状态

它更接近：

**dynamic planner + subagent runtime + guardrail middleware**

### 4.2 deer-flow 值得借鉴的点

最值得借鉴的是：

1. 复杂任务由主 agent 动态拆分
2. 子任务通过一级工具 `task` 分派
3. 系统对并发做硬限制，而不是只靠 prompt
4. 状态以 `todo/artifact/thread state` 表达，而不是重 workflow 引擎

### 4.3 deer-flow 不应直接照搬

不建议原样照搬 deer-flow。

原因：

- `smartclaw` 已经有自己的 runtime、gateway、capability pack、observability
- 直接迁 runtime 会破坏当前系统连续性

正确方式是：

**借鉴 deer-flow 的动态编排思想，用在 `smartclaw` 现有架构上。**

---

## 5. 目标架构

目标架构如下：

### 5.1 总体分层

#### A. Tool / MCP 层

职责：

- 提供原子能力
- 面向外部系统、命令、数据读取、执行动作

示例：

- 基线检查
- 弱口令检查
- 漏洞扫描
- 执行加固
- 生成前端代码
- 生成 API 文档
- 查询工单 / CMDB / 漏洞平台

说明：

后续新增底层能力时，允许新增这层代码。

#### B. Skill 层

职责：

- 对 tool 做业务化封装
- 给 planner 提供更稳定的执行语义

示例：

- `baseline-check-skill`
- `vuln-remediation-skill`
- `frontend-generate-skill`
- `api-design-skill`

说明：

skill 仍然是“能力封装”，不是全局流程。

#### C. Capability Pack 层

职责：

- 定义业务域边界和治理规则
- 限定可用 tools / skills
- 指定默认模式和约束

示例：

- `security-governance-pack`
- `dev-delivery-pack`
- `ops-inspection-pack`

定义内容包括：

- `preferred_mode`
- `allowed_tools`
- `denied_tools`
- `schema_enforced`
- `approval_required`
- `concurrency_limits`
- `retry_on_error`

#### D. Step Registry 层

职责：

- 注册“可被动态规划选中的步骤模板”
- 提供步骤输入输出合同

注意：

这里的 `step` 不是固定 workflow 节点，而是：

**planner 可选用的步骤能力目录**

示例：

- `baseline_check`
- `weak_password_check`
- `vulnerability_scan`
- `hardening`
- `verification`
- `report_generation`
- `api_design`
- `backend_generate`

每个 step 只描述：

- 它是什么
- 它需要什么输入
- 它会产出什么输出
- 推荐使用哪些 skill/tool
- 是否可并行
- 是否属于高风险步骤

#### E. Planner / Orchestrator 层

职责：

- 根据任务目标动态选取 step
- 按依赖和当前上下文决定执行顺序
- 触发并行分派和汇总
- 管理 todo / phase / batch

说明：

这一层应复用当前 `orchestrator_graph`、`plan_manager`、`dispatch_tasks` 的框架能力，而不是另起一套 runtime。

#### F. Artifact / Context 层

职责：

- 统一沉淀中间产物
- 让上一步输出稳定成为下一步输入

示例：

- `baseline_report`
- `weak_password_findings`
- `vuln_report`
- `hardening_plan`
- `verification_result`
- `api_contract`
- `db_schema`

---

## 6. 核心设计原则

### 6.1 动态规划优先

默认不写死固定流程。

planner 应根据：

- 用户目标
- 当前 capability pack
- 已有附件与上下文
- 当前 artifacts
- step registry 中的候选步骤

动态决定：

- 要不要用某个 step
- 哪些先做
- 哪些并行
- 哪些跳过
- 是否回退

### 6.2 约束配置化

动态规划不等于完全放飞。

约束要通过配置表达，而不是写死到 prompt 里。

约束来源包括：

- capability pack
- model capability
- step definition
- runtime dispatch policy

### 6.3 流程模板是辅助，不是主线

允许存在“流程模板”或“推荐依赖模板”，但它们应是：

- soft guidance
- candidate topology

而不是强制顺序。

### 6.4 上下游依赖靠 artifact，不靠聊天文本

步骤之间的输入传递必须靠结构化 artifact。

否则：

- planner 不稳定
- 下游无法稳定消费上游结果
- 难以审计

---

## 7. Step Registry 设计

### 7.1 为什么需要 Step Registry

如果没有 step registry，planner 只能：

- 靠 prompt 猜有哪些步骤
- 靠自然语言猜输入输出

这在复杂业务场景中会非常不稳定。

Step Registry 的作用是：

- 给 planner 一个受控的“步骤词典”
- 但不强制固定顺序

### 7.2 Step Definition 结构

建议每个 step 定义如下字段：

```yaml
id: baseline_check
name: 基线检查
domain: security
description: 对目标资产执行基线检查并输出结构化发现

applicable_when:
  scenario_types: [inspection, hardening]
  keywords: [基线, 巡检, 合规]

inputs:
  required:
    - asset_scope
  optional:
    - baseline_profile
    - previous_findings

outputs:
  - baseline_report
  - baseline_findings

artifacts_produced:
  baseline_report:
    schema: baseline_report_v1

execution:
  preferred_skill: baseline-check-skill
  allowed_tools: [check_baseline]
  can_run_parallel: true
  risk_level: low

next_step_hints:
  on_success:
    - weak_password_check
    - vulnerability_scan
  on_findings:
    - hardening
```

### 7.3 Step Registry 的定位

Step Registry 不是 workflow 文件。

它更像：

- 可用步骤目录
- 步骤输入输出合同库
- planner 的候选空间

---

## 8. Artifact / IO Contract 设计

### 8.1 必须统一结构化产物

每个 step 的输出都要沉淀成 artifact，而不是只写一段自由文本。

例如：

```json
{
  "artifact_id": "baseline_report",
  "version": "v1",
  "producer_step": "baseline_check",
  "status": "completed",
  "summary": "已完成基线检查，发现 6 项不符合项",
  "data": {
    "findings": [...],
    "risk_level": "high",
    "need_hardening": true
  }
}
```

### 8.2 输入映射规则

planner 不应把上游文本原文塞给下游，而应优先走 artifact 映射：

- `baseline_report` -> `hardening` 的输入
- `api_contract` -> `backend_generate` 的输入
- `frontend_spec + db_schema` -> `api_design` 的输入

### 8.3 Context 分层

建议上下文分三层：

1. `conversation_context`
2. `artifact_context`
3. `capability_context`

其中真正用于流程推进的主输入应是：

**artifact_context**

---

## 9. Planner / Orchestrator 设计

### 9.1 Planner 的职责

planner 应负责：

1. 理解目标
2. 识别适用 capability pack
3. 从 step registry 选候选步骤
4. 根据现有输入和 artifacts 动态装配执行图
5. 生成 todos
6. 判定并行 / 串行 / 条件推进

### 9.2 执行形态

建议保留当前 `classic / orchestrator / auto`。

其中：

- `classic`
  适合简单任务
- `orchestrator`
  适合复杂动态编排任务
- `auto`
  按 mode router + capability pack + step count 动态判断

### 9.3 Orchestrator 内部状态

建议继续沿用当前这些状态：

- `plan`
- `todos`
- `current_phase`
- `dispatch_batches`
- `task_results`

但进一步扩展：

- `candidate_steps`
- `resolved_artifacts`
- `execution_constraints`
- `selected_pack`

### 9.4 并行与分批

应沿用当前 `dispatch_tasks` 思路：

- planner 先决定哪些 todo 可并行
- dispatch policy 分 batch
- subagent executor 跑子任务
- review 阶段根据结果推进下一步

这与 deer-flow 的思想一致，但保留 SmartClaw 自有 runtime。

---

## 10. Capability Pack 与 Step 的关系

### 10.1 Capability Pack 不负责写死流程

pack 的职责应是：

- 定义业务域边界
- 定义允许使用哪些 step/tool/skill
- 定义治理规则

而不是：

- 规定每次必须固定按某条链执行

### 10.2 推荐关系

建议 pack 中新增：

- `allowed_steps`
- `denied_steps`
- `preferred_step_groups`
- `entry_hints`

示例：

```yaml
name: security-governance
preferred_mode: orchestrator
allowed_steps:
  - baseline_check
  - weak_password_check
  - vulnerability_scan
  - hardening
  - verification
  - report_generation
concurrency_limits:
  inspection: 3
  remediation: 1
```

这样后续新增业务域时，主要变更是 pack 和 step 配置，而不是 runtime 代码。

---

## 11. 典型场景如何动态运行

### 11.1 安全治理场景

用户输入：

“帮我跑基线、弱口令、漏洞检查，根据结果决定是否加固，最后输出报告。”

planner 动态决策：

1. 识别 `security-governance-pack`
2. 候选步骤：
   - `baseline_check`
   - `weak_password_check`
   - `vulnerability_scan`
   - `hardening`
   - `verification`
   - `report_generation`
3. 判断前三个检查步骤可并行
4. 汇总 findings 后决定是否需要 `hardening`
5. 若触发加固，则进入 `verification`
6. 最终生成报告

注意：

这里不是固定写死 `A -> B -> C`，而是：

- 检查步骤并行
- 是否进入加固由结果决定
- 是否需要再验证由风险等级决定

### 11.2 开发场景

用户输入：

“根据需求生成表结构、API 设计和后端代码。”

planner 动态决策：

1. 识别 `dev-delivery-pack`
2. 候选步骤：
   - `table_design`
   - `api_design`
   - `backend_generate`
   - `api_doc_generate`
3. 若缺前置信息，则先发 clarification
4. 若 `table_design` 与 `frontend_spec` 互相独立，可先并行准备
5. `api_design` 依赖上游 artifacts 完成后再执行
6. 再推进 `backend_generate`

同样不是写死 workflow，而是动态装配依赖。

---

## 12. 扩展模型

### 12.1 以后新增业务时，通常只做这些

理想路径：

1. 新增 tool / mcp
2. 新增 skill
3. 新增 step definition
4. 新增 capability pack

### 12.2 什么时候才需要改核心代码

只在以下情况修改核心：

1. 新增通用编排机制
   - 全局审批模型
   - 回滚机制
   - 统一补偿逻辑

2. 新增 artifact 路由机制
   - 新的跨步骤产物映射规则

3. 新增 runtime 级策略
   - 新的并发策略
   - 新的调度策略

换句话说：

**新增业务场景本身不应成为改核心代码的理由。**

---

## 13. 对当前 SmartClaw 的具体改造建议

### 13.1 保留现有核心

继续保留：

- `mode_router`
- `orchestrator_graph`
- `dispatch_tasks`
- `capability pack`
- `subagent`
- `gateway`
- `context / uploads / observability`

### 13.2 需要新增的通用层

新增但保持通用：

1. `step_registry`
2. `artifact_store`
3. `artifact_mapping`
4. `planner_context_builder`
5. `pack_step_policy`

### 13.3 Orchestrator 需要增强的点

当前 orchestrator 更偏：

- 初始 plan
- todo 执行
- synthesize

建议增强为：

- 候选 step 解析
- 基于 artifact 的输入装配
- todo 不是纯 prompt 生成，而是 step-aware
- review 阶段可重新规划下一批 steps

也就是：

**从“task fan-out orchestrator”增强为“step-aware dynamic orchestrator”。**

---

## 14. 推荐实施顺序

### Phase 1：补通用抽象

目标：

- 引入 `step registry`
- 引入 `artifact` 基础结构
- pack 可约束 steps

此阶段不追求所有场景都可用，先把核心抽象对齐。

### Phase 2：让 orchestrator 认识 step

目标：

- planner 生成 step-aware todos
- dispatch 任务与 step definition 挂钩
- review 阶段按 artifact 动态推进

### Phase 3：选两个业务域试点

建议：

1. `security-governance`
2. `dev-delivery`

验证：

- 同一编排框架是否能覆盖两个完全不同业务域
- 扩展新场景是否主要靠配置

### Phase 4：做平台化接入

目标：

- 把现有各业务页面从“流程主脑”降级成“输入输出界面”
- 真正让 SmartClaw 成为编排中枢

---

## 15. 最终判断

针对你的最终目标，最合适的框架方向不是：

- 固定 workflow 引擎
- 也不是完全自由的无边界 planner

而是：

## SmartClaw 通用动态编排框架

特征如下：

- 动态规划
- 配置驱动约束
- step registry 作为候选步骤目录
- capability pack 负责业务域边界
- artifact 负责上下游输入输出传递
- subagent 负责并行执行

最终效果应是：

- 新增业务时尽量不改核心代码
- 主要靠新增 `tools / skills / mcp / step definitions / capability packs`
- 同一框架可覆盖开发、安全、运维、治理等多种业务域

这才符合 `smartclaw` 作为“超级智能体框架”的定位。
