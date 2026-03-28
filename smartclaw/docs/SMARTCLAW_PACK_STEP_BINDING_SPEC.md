# SmartClaw Capability Pack x Step Registry Binding 规范

## 1. 目标

本文档定义：

- `capability pack` 如何约束 `step registry`
- planner 如何在 pack 边界内做动态规划
- 后续新增业务时，哪些通过配置扩展，哪些才需要修改核心代码

本文档解决的问题不是“把流程写死”，而是：

> 在动态规划前提下，如何给 planner 提供稳定、可治理、可审计的步骤选择边界

---

## 2. 核心结论

`capability pack` 不负责写死流程顺序。  
它负责定义：

- 允许哪些步骤
- 禁止哪些步骤
- 哪些步骤优先
- 哪些步骤需要审批
- 哪些步骤有并发/重试/风险边界

而 `step registry` 负责定义：

- 每个 step 的输入输出合同
- step 的语义
- step 推荐调用哪些 tools / skills / mcp

所以：

- `pack` = 业务域边界与治理策略
- `step` = 可被 planner 动态选择的步骤模板
- `planner` = 在 pack 允许范围内动态编排

---

## 3. 整体关系图

```mermaid
flowchart LR
    U[User Goal] --> CP[Capability Pack Resolver]
    CP --> PK[Active Capability Pack]
    PK --> SR[Step Registry Filter]
    SR --> CAND[Candidate Steps]
    CAND --> PL[Planner / Orchestrator]
    PL --> EX[Step Executor]
    EX --> AR[Artifact Store]
    AR --> PL
```

---

## 4. Pack 的职责边界

Capability Pack 应负责：

- 识别业务域
- 收敛 planner 可选能力边界
- 指定默认偏好
- 指定风险与治理策略

Capability Pack 不负责：

- 写死完整执行顺序
- 取代 planner 做每一步决策
- 直接执行工具

---

## 5. Step Registry 的职责边界

Step Registry 应负责：

- 注册可复用步骤模板
- 定义 step 输入输出
- 声明 step 特征
- 支持 pack 进行过滤与引用

Step Registry 不负责：

- 决定当前是否执行该 step
- 绑定具体业务 pack
- 保存执行状态

---

## 6. Pack 与 Step 的绑定原则

### 6.1 默认白名单

对于生产业务，建议 pack 默认使用白名单模式。

也就是：

- 只允许 pack 明确声明的 step 被 planner 看见
- 不在列表内的 step 视为不可用

### 6.2 可选黑名单

对通用探索型场景，可允许先按 domain/type 放开，再通过黑名单排除。

### 6.3 只绑定能力边界，不绑定固定顺序

例如：

- `security-governance-pack` 可以允许：
  - `baseline_check`
  - `weak_password_check`
  - `vulnerability_scan`
  - `security_summary`
  - `hardening`
  - `verification`
  - `report_generation`

但不要求必须按写死顺序运行。

Planner 仍可以：

- 先并行检查
- 根据结果决定是否做加固
- 根据验证结果决定是否回退

---

## 7. Pack 建议结构

```yaml
id: "security-governance-pack"
name: "Security Governance"
domain: "security"
preferred_mode: "orchestrator"
step_binding:
  policy: "allow_list"
  allowed_steps:
    - "baseline_check"
    - "weak_password_check"
    - "vulnerability_scan"
    - "security_summary"
    - "hardening"
    - "verification"
    - "report_generation"
  blocked_steps:
    - "code_generation"
  preferred_steps:
    - "security_summary"
    - "verification"
  approval_required_steps:
    - "hardening"
  retry_policy:
    hardening:
      max_retries: 1
  concurrency_policy:
    inspection: 3
    remediation: 1
```

---

## 8. Step 绑定字段建议

建议 pack 中 `step_binding` 至少支持以下字段：

| 字段 | 含义 |
| --- | --- |
| `policy` | `allow_list` / `domain_filter` / `mixed` |
| `allowed_steps` | 允许的 step ids |
| `blocked_steps` | 禁止的 step ids |
| `preferred_steps` | 优先选择的 step ids |
| `required_steps` | 特定场景必须包含的 step ids |
| `approval_required_steps` | 执行前需审批的 step |
| `retry_policy` | step 级重试策略 |
| `concurrency_policy` | step 分组并发限制 |
| `risk_overrides` | 风险级别覆盖 |

---

## 9. Planner 如何消费 Pack-Step 绑定

Planner 在一次请求中应按以下顺序消费配置：

1. 识别 capability pack
2. 从 step registry 中取出所有 step
3. 根据 pack 进行过滤
4. 对剩余 step 打分
5. 按当前任务目标、已有 artifact、风险状态动态选择下一步

```mermaid
flowchart TD
    Start[User Goal] --> ResolvePack[Resolve Pack]
    ResolvePack --> LoadSteps[Load Step Registry]
    LoadSteps --> Filter[Filter by Pack Rules]
    Filter --> Rank[Rank Preferred Steps]
    Rank --> Check[Check Preconditions and Artifacts]
    Check --> Decide[Planner Selects Next Step(s)]
```

---

## 10. Step 候选选择逻辑

对于每个 step，planner 应同时考虑：

- 是否被 pack 允许
- 当前输入是否满足
- 当前 artifacts 是否已具备前置条件
- 风险级别是否允许
- 是否需要人工确认
- 是否和当前目标相关

建议选择逻辑采用“过滤 + 排序”，不是“硬编码分支”。

---

## 11. 推荐的 Step 评分维度

可采用如下评分维度：

- `goal_match_score`
- `artifact_readiness_score`
- `pack_preference_score`
- `risk_penalty`
- `parallelizability_score`
- `tool_availability_score`

最终由 planner 综合这些维度选下一步。

---

## 12. 开发场景示例

### 12.1 Pack

```yaml
id: "dev-delivery-pack"
domain: "development"
step_binding:
  policy: "allow_list"
  allowed_steps:
    - "requirement_analysis"
    - "frontend_generate"
    - "table_design"
    - "api_design"
    - "backend_generate"
    - "api_doc_generate"
  preferred_steps:
    - "requirement_analysis"
    - "api_design"
```

### 12.2 运行效果

用户说：

> 根据需求生成接口设计和后端代码

planner 可能动态决定：

- 若没有结构化需求，先做 `requirement_analysis`
- 若已有表结构，则跳过 `table_design`
- 若只需要接口和后端，可不执行 `frontend_generate`

这说明：

pack 定义边界，planner 决定实际路径。

---

## 13. 安全治理场景示例

### 13.1 Pack

```yaml
id: "security-governance-pack"
domain: "security"
step_binding:
  policy: "allow_list"
  allowed_steps:
    - "baseline_check"
    - "weak_password_check"
    - "vulnerability_scan"
    - "security_summary"
    - "hardening"
    - "verification"
    - "report_generation"
  approval_required_steps:
    - "hardening"
  concurrency_policy:
    inspection: 3
    remediation: 1
```

### 13.2 运行效果

用户说：

> 跑基线、弱口令、漏洞检查，并根据结果动态加固

planner 可以：

- 并行运行三个检查 step
- 汇总 findings
- 若无需整改则跳过 `hardening`
- 若执行整改则进入 `verification`

这不是 fixed workflow，而是 pack 约束下的动态规划。

---

## 14. 新增业务时什么需要改

理想情况下，新增业务时只需要：

- 新增 tools / skills / mcp
- 新增 capability pack
- 新增 step definitions

通常不需要：

- 修改 planner 主代码
- 修改 orchestrator 主循环
- 修改 gateway 主逻辑

只有在新增“通用调度机制”时，才应修改核心代码。

---

## 15. 推荐目录结构

```text
capability_packs/
  security-governance/
    pack.yaml
  dev-delivery/
    pack.yaml

step_registry/
  baseline_check.yaml
  weak_password_check.yaml
  vulnerability_scan.yaml
  api_design.yaml
  backend_generate.yaml
```

---

## 16. 与固定 Workflow 的区别

| 方案 | 特点 |
| --- | --- |
| 固定 workflow | 顺序固定、灵活性差、适合刚性流程 |
| 纯自由规划 | 灵活，但不稳定、难审计 |
| Pack + Step + Planner | 动态规划 + 规则边界，适合 SmartClaw |

---

## 17. 最终原则

Capability Pack x Step Registry Binding 的目标是：

- 不把流程写死
- 不让 planner 完全无边界
- 让新增业务主要靠配置扩展

一句话概括：

> pack 定边界，step 定能力，planner 定路径

---

## 18. 下一步建议

在本文档之后，建议继续完成：

1. `Planner Input Resolution Spec`
2. `Runtime State & Observability Spec`

