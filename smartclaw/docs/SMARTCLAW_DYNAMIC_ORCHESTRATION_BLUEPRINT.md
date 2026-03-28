# SmartClaw 通用动态编排蓝图

## 1. 文档目标

本文档以“图 + 关键说明”的方式，描述 `smartclaw` 面向多业务域的通用动态编排框架。

目标是回答 4 个问题：

1. `smartclaw` 未来的核心架构应该长什么样
2. 用户请求进入后，系统如何动态规划、拆分、调度、汇总
3. 为什么后面新增业务时，主要应靠配置扩展，而不是继续改核心代码
4. 如何把开发场景、安全治理场景都放进同一套框架中

---

## 2. 总体判断

`smartclaw` 的目标形态不是固定 workflow 引擎，而是：

**动态规划中枢 + 配置驱动约束 + 通用执行运行时**

一句话概括：

- planner 决定“做什么”
- orchestrator 决定“怎么分派和推进”
- tools / skills / mcp 决定“怎么执行”
- capability pack / step registry / artifact 决定“怎么稳定扩展”

---

## 3. 总体架构图

```mermaid
flowchart LR
    U[用户 / 页面 / API] --> G[Gateway / Chat Request]
    G --> MR[Mode Router]
    G --> CR[Capability Resolver]
    G --> CB[Context Builder]

    MR --> ORCH[Planner / Orchestrator]
    CR --> ORCH
    CB --> ORCH

    ORCH --> SR[Step Registry]
    ORCH --> AS[Artifact Store]
    ORCH --> DP[Dispatch Policy]
    ORCH --> SUB[Subagent Runtime]

    SUB --> SK[Skills]
    SUB --> TL[Tools]
    SUB --> MCP[MCP / 外部系统]

    TL --> AS
    SK --> AS
    MCP --> AS
    SUB --> AS

    AS --> ORCH
    ORCH --> SYN[Synthesize / Final Answer]
    SYN --> G
    G --> U
```

### 关键理解

- `Gateway` 只是入口，不是流程主脑
- `Mode Router` 决定走 `classic` 还是 `orchestrator`
- `Capability Resolver` 决定当前业务域边界
- `Planner / Orchestrator` 是核心
- `Step Registry` 提供“可被动态规划选中的步骤目录”
- `Artifact Store` 负责上下游输入输出传递
- `Subagent Runtime` 负责真正并行跑子任务

---

## 4. 分层关系图

```mermaid
flowchart TD
    A[业务域层\nCapability Pack] --> B[步骤层\nStep Registry]
    B --> C[编排层\nPlanner / Orchestrator]
    C --> D[执行层\nSkills / Tools / MCP / Subagents]
    D --> E[产物层\nArtifacts / Structured Outputs]
    E --> C
```

### 分层职责

#### Capability Pack

负责：

- 场景边界
- 允许的工具 / 技能 / 步骤
- 审批 / 重试 / schema / 并发等治理规则

#### Step Registry

负责：

- 注册一批“可选步骤模板”
- 每个步骤的输入输出合同
- 每个步骤的执行偏好

#### Planner / Orchestrator

负责：

- 动态选步骤
- 规划依赖
- 并行与分批调度
- 结果汇总与继续推进

#### Skills / Tools / MCP / Subagents

负责：

- 真正执行动作
- 连接外部系统
- 输出结构化结果

#### Artifacts

负责：

- 沉淀上一步结果
- 成为下一步输入
- 避免纯聊天文本传递导致漂移

---

## 5. 请求进入后的动态流程图

```mermaid
flowchart TD
    A[用户请求] --> B[识别 mode]
    B --> C[识别 capability pack]
    C --> D[构建上下文\n消息 + 附件 + 历史 + artifacts]
    D --> E[Planner 分析目标]
    E --> F[从 Step Registry 选择候选步骤]
    F --> G[生成 plan / todos]
    G --> H{是否可并行}

    H -- 是 --> I[按 Dispatch Policy 分 batch]
    H -- 否 --> J[串行执行当前步骤]

    I --> K[Subagent 分派执行]
    J --> K

    K --> L[写回 artifacts / task_results]
    L --> M{是否完成目标}
    M -- 否 --> N[基于最新 artifacts 重新规划下一轮]
    N --> F
    M -- 是 --> O[综合所有结果]
    O --> P[返回最终结果]
```

### 这张图表达的重点

- 不是固定顺序执行
- 每轮执行后都可以重新规划
- `artifacts` 是下一轮规划的重要输入
- planner 可以动态决定跳过、并行、回退、继续

---

## 6. 为什么不能只靠自由规划

```mermaid
flowchart LR
    A[完全自由规划] --> B[灵活]
    A --> C[不稳定]
    A --> D[难审计]
    A --> E[上下游输入输出漂移]

    F[固定 workflow] --> G[稳定]
    F --> H[可审计]
    F --> I[不灵活]
    F --> J[扩展成本高]

    K[动态规划 + 配置约束] --> L[兼顾灵活与稳定]
```

### 推荐路线

`smartclaw` 应走中间路线：

**动态规划 + 配置约束**

而不是：

- 完全自由
- 或完全写死

---

## 7. Capability Pack、Step、Tool、Skill 的关系图

```mermaid
flowchart LR
    CP[Capability Pack] -->|约束| ST[Step Definitions]
    CP -->|限制| SK[Skills]
    CP -->|限制| TL[Tools]
    CP -->|治理| OR[Orchestrator]

    ST -->|推荐执行| SK
    ST -->|推荐执行| TL

    SK --> TL
    TL --> MCP[MCP / 外部系统]

    OR --> ST
    OR --> SK
    OR --> TL
```

### 一句话区分

- `tool`：原子动作
- `skill`：能力封装
- `step`：步骤模板
- `capability pack`：业务域边界和治理规则
- `orchestrator`：动态调度引擎

---

## 8. Step Definition 的位置

你前面担心 `step` 会不会把流程写死。

答案是：

**不会，只要它被定义成“候选步骤目录”，而不是固定顺序节点”。**

```mermaid
flowchart TD
    A[Step Registry] --> B[baseline_check]
    A --> C[weak_password_check]
    A --> D[vulnerability_scan]
    A --> E[hardening]
    A --> F[verification]
    A --> G[report_generation]
    A --> H[frontend_generate]
    A --> I[table_design]
    A --> J[api_design]
    A --> K[backend_generate]
```

planner 在运行时做的是：

- 从这个目录里挑候选步骤
- 根据当前目标和输入动态组装执行图

而不是：

- 预先写死 `A -> B -> C`

---

## 9. Artifact 流转图

```mermaid
flowchart LR
    S1[Step A] --> O1[Artifact A]
    O1 --> S2[Step B]
    O1 --> S3[Step C]
    S2 --> O2[Artifact B]
    S3 --> O3[Artifact C]
    O2 --> S4[Step D]
    O3 --> S4
    S4 --> O4[Artifact D]
```

### 这层为什么重要

没有 `artifact`，步骤之间就只能靠聊天文本传递上下文。

后果是：

- 输入不稳定
- 下游难消费
- 结果难复用
- planner 很难做稳定判断

所以：

**通用动态编排框架的核心之一，是 artifact 总线。**

---

## 10. 当前 SmartClaw 对应关系图

```mermaid
flowchart TD
    A[当前 SmartClaw 已有能力] --> B[Mode Router]
    A --> C[Orchestrator Graph]
    A --> D[Dispatch Tasks]
    A --> E[Capability Pack]
    A --> F[Uploads / OCR / Vision]
    A --> G[Observability / Execution]

    B --> H[未来增强]
    C --> H
    D --> H
    E --> H

    H[通用动态编排框架]
    H --> I[新增 Step Registry]
    H --> J[新增 Artifact Model]
    H --> K[新增 Artifact Mapping]
    H --> L[增强 Planner 为 Step-aware]
```

### 意味着什么

你现在不是从零开始。

你已经有：

- 动态模式分流
- orchestrator 运行骨架
- subagent 批量分派
- capability pack 治理
- 上传 / OCR / vision / 结构化输出

缺的是：

- `Step Registry`
- `Artifact` 模型
- step-aware planner

---

## 11. 开发场景的动态编排示意

```mermaid
flowchart TD
    A[用户: 根据需求生成后端接口和文档] --> B[识别 dev-delivery-pack]
    B --> C[候选 steps]
    C --> C1[table_design]
    C --> C2[api_design]
    C --> C3[backend_generate]
    C --> C4[api_doc_generate]

    C1 --> D1[db_schema]
    C2 --> D2[api_contract]
    D1 --> C2
    D2 --> C3
    D2 --> C4
```

重点：

- 不是固定先后写死
- planner 可以根据输入完整度决定是否跳过 `table_design`
- `api_doc_generate` 是否执行也可以由目标决定

---

## 12. 安全治理场景的动态编排示意

```mermaid
flowchart TD
    A[用户: 跑基线/弱口令/漏洞检查并根据结果加固] --> B[识别 security-governance-pack]
    B --> C[候选 steps]
    C --> C1[baseline_check]
    C --> C2[weak_password_check]
    C --> C3[vulnerability_scan]
    C --> C4[hardening]
    C --> C5[verification]
    C --> C6[report_generation]

    C1 --> D1[baseline_report]
    C2 --> D2[weak_password_findings]
    C3 --> D3[vuln_report]

    D1 --> E[planner review]
    D2 --> E
    D3 --> E

    E -->|need remediation| C4
    E -->|no remediation| C6

    C4 --> D4[hardening_result]
    D4 --> C5
    C5 --> D5[verification_report]
    D5 --> C6
```

重点：

- 检查步骤可以并行
- 是否进入加固由结果决定
- 是否需要验证由风险状态决定
- 这就是动态编排，不是固定脚本

---

## 13. 后续扩展时哪些要改，哪些不该改

### 13.1 理想情况下，只改配置或能力注册

新增业务时，优先只做：

```mermaid
flowchart LR
    A[新增业务场景] --> B[新增 Tool / MCP]
    A --> C[新增 Skill]
    A --> D[新增 Capability Pack]
    A --> E[新增 Step Definitions]
```

### 13.2 只有这些情况才改核心代码

```mermaid
flowchart LR
    A[新增通用框架能力] --> B[改核心代码]
    A --> C[如全局审批]
    A --> D[如统一回滚]
    A --> E[如新的 Artifact 映射机制]
    A --> F[如新的调度策略]
```

换句话说：

**新增业务本身，不应成为改核心代码的理由。**

---

## 14. 推荐实施路线图

```mermaid
flowchart TD
    A[Phase 1\n定规范] --> B[Step Registry 规范]
    A --> C[Artifact 规范]
    A --> D[Pack-Step 关系规范]

    B --> E[Phase 2\n增强 Orchestrator]
    C --> E
    D --> E

    E --> F[Step-aware Planner]
    E --> G[Artifact Mapping]
    E --> H[Dynamic Re-planning]

    F --> I[Phase 3\n双场景试点]
    G --> I
    H --> I

    I --> J[开发场景试点]
    I --> K[安全治理场景试点]

    J --> L[Phase 4\n平台化接入]
    K --> L
```

### 顺序解释

当前最合理的下一步仍然是：

1. 定规范
2. 再改 orchestrator
3. 再做试点场景

因为如果规范先不清楚，后面的运行时增强很容易返工。

---

## 15. 最终目标图

```mermaid
flowchart LR
    U[用户目标] --> P[SmartClaw Planner]
    P -->|选择业务域| CP[Capability Pack]
    P -->|选择步骤| SR[Step Registry]
    P -->|调度执行| EX[Subagents / Skills / Tools / MCP]
    EX --> AR[Artifacts]
    AR --> P
    P --> R[最终结果]
```

### 最终形态

你真正要的不是：

- 多个割裂的业务页面
- 多个固定流程脚本

而是：

**一个通用的动态编排中枢**

满足：

- 多业务域复用
- 动态规划
- 可并行分派
- 结构化产物流转
- 以后主要靠新增 `tools / skills / mcp / step / pack` 扩展

---

## 16. 结论

结合当前 `smartclaw` 的实现，以及你要的最终目标，推荐架构方向是：

### SmartClaw 通用动态编排框架

核心特点：

1. 动态规划，而不是固定 workflow
2. 配置驱动约束，而不是无边界自由规划
3. Step Registry 作为候选步骤目录
4. Artifact 作为上下游输入输出总线
5. Capability Pack 作为业务域边界和治理层
6. Orchestrator 作为统一调度中枢

这条路线最符合你的目标：

**后面尽量不改核心代码，主要靠新增 tools、skills、mcp 和配置来扩展。**
