# 实施计划：LLM 决策可观测性（Decision Trace）

## 概述

基于需求和设计文档，将 Decision Trace 系统的实现分解为增量式编码任务。每个任务在前一个任务的基础上构建，最终将所有组件串联集成。使用 Python 实现，属性测试使用 Hypothesis 库。

## 任务

- [x] 1. 实现 DecisionRecord 数据结构和 DecisionType 枚举
  - [x] 1.1 创建 `smartclaw/smartclaw/observability/decision_record.py`
    - 实现 `DecisionType` 枚举（`tool_call`、`final_answer`、`supervisor_route`）
    - 实现 `DecisionRecord` frozen dataclass，包含必填字段（timestamp、iteration、decision_type、input_summary、reasoning）和可选字段（tool_calls、target_agent、session_key）
    - 实现 `to_dict()` 方法，将 `decision_type` 序列化为字符串值
    - 实现 `from_dict()` 类方法，包含必填字段校验（缺失时抛出 `ValueError`）
    - 实现 `_utc_now_iso()` 辅助函数
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 9.4_

  - [x] 1.2 编写 DecisionRecord 序列化往返属性测试
    - 创建 `smartclaw/tests/observability/test_decision_record_props.py`
    - 使用 `@st.composite` 构建 `DecisionRecord` 生成器
    - **Property 1: DecisionRecord 序列化往返一致性** — `from_dict(r.to_dict()).to_dict() == r.to_dict()`
    - **验证: Requirements 1.5, 9.3**

  - [x] 1.3 编写 JSON 序列化往返属性测试
    - **Property 2: JSON 序列化往返一致性** — `json.loads(json.dumps(r.to_dict())) == r.to_dict()`
    - **验证: Requirements 9.1, 9.2**

  - [x] 1.4 编写 from_dict 缺少必填字段属性测试
    - **Property 3: from_dict 缺少必填字段时抛出 ValueError**
    - **验证: Requirements 9.4**

- [x] 2. 实现 DecisionTraceCollector 模块级单例
  - [x] 2.1 创建 `smartclaw/smartclaw/observability/decision_collector.py`
    - 实现模块级存储 `_store: dict[str, list[DecisionRecord]]`
    - 实现 `add(record)` 异步方法：存储记录 + 通过 Diagnostic Bus 发布 `decision.captured` 事件
    - 实现 `get_decisions(session_key)` 方法：返回按时间戳升序排列的记录列表
    - 实现 `clear(session_key)` 方法：清除指定会话或全部记录
    - 实现每个 session 最多 200 条记录的上限控制
    - 未提供 session_key 时使用默认键 `"__default__"`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.3_

  - [x] 2.2 编写决策记录存储往返属性测试
    - 创建 `smartclaw/tests/observability/test_decision_collector_props.py`
    - **Property 6: 决策记录存储往返** — `add()` 后 `get_decisions()` 应包含该记录
    - **验证: Requirements 4.1, 11.2**

  - [x] 2.3 编写决策记录时间戳升序不变量属性测试
    - **Property 7: 决策记录时间戳升序不变量** — `get_decisions()` 返回的列表时间戳单调非递减
    - **验证: Requirements 4.3, 11.4**

  - [x] 2.4 编写每个 session 最多 200 条记录不变量属性测试
    - **Property 8: 每个 session 最多 200 条记录不变量** — 无论添加多少条，`get_decisions()` 长度不超过 200
    - **验证: Requirements 4.5**

  - [x] 2.5 编写决策事件通过 Diagnostic Bus 发布属性测试
    - **Property 10: 决策事件通过 Diagnostic Bus 发布** — `add()` 后订阅者应收到 `decision.captured` 事件
    - **验证: Requirements 5.1**

- [x] 3. 检查点 — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [x] 4. 在 reasoning_node 中集成决策捕获
  - [x] 4.1 修改 `smartclaw/smartclaw/agent/nodes.py` 的 `reasoning_node` 函数
    - 在 LLM 调用成功后、返回结果前，插入 try/except 包裹的决策捕获逻辑
    - 根据 `response.tool_calls` 是否存在，设置 `decision_type` 为 `tool_call` 或 `final_answer`
    - 从消息列表中提取最近一条消息内容作为 `input_summary`（截断到 512 字符）
    - 从 `response.content` 提取 `reasoning`（截断到 2048 字符）
    - 当 LLM 返回工具调用时，记录所有 `tool_calls`（包含 tool_name 和 tool_args）
    - 异常时静默处理，不影响 Agent 主流程
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 10.1, 10.2, 10.3_

  - [x] 4.2 编写 LLM 调用决策捕获正确性属性测试
    - 创建 `smartclaw/tests/observability/test_decision_capture_props.py`
    - **Property 4: LLM 调用决策捕获正确性** — tool_calls 存在时 decision_type 为 tool_call，否则为 final_answer；reasoning 来自 AIMessage.content；input_summary 来自最近消息
    - **验证: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

  - [x] 4.3 编写字段长度截断不变量属性测试
    - **Property 9: 字段长度截断不变量** — input_summary ≤ 512 字符，reasoning ≤ 2048 字符
    - **验证: Requirements 10.3**

- [x] 5. 在 _supervisor_node 中集成决策捕获
  - [x] 5.1 修改 `smartclaw/smartclaw/agent/multi_agent.py` 的 `_supervisor_node` 方法
    - 在解析 supervisor 决策后，插入 try/except 包裹的决策捕获逻辑
    - 当路由目标为具体 Agent 时，设置 `decision_type` 为 `supervisor_route`，`target_agent` 为 Agent 名称
    - 当路由目标为 `"done"` 时，设置 `decision_type` 为 `final_answer`
    - 将 Supervisor LLM 响应内容记录到 `reasoning` 字段（截断到 2048 字符）
    - 异常时静默处理，不影响主流程
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 10.1, 10.2_

  - [x] 5.2 编写 Supervisor 路由决策捕获正确性属性测试
    - **Property 5: Supervisor 路由决策捕获正确性** — 路由到具体 Agent 时 decision_type 为 supervisor_route，路由到 done 时为 final_answer
    - **验证: Requirements 3.1, 3.2, 3.3, 3.4**

- [x] 6. 检查点 — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [x] 7. 实现 Decision SSE 端点和 REST API
  - [x] 7.1 修改 `smartclaw/smartclaw/gateway/app.py` 添加 Decision SSE 端点
    - 添加模块级广播队列 `_decision_event_queues`
    - 实现 `_broadcast_decision_event()` 函数（复用 hook-events 的广播模式）
    - 在 `lifespan` 中注册 Diagnostic Bus `decision.captured` 事件订阅
    - 在 `create_app` 中添加 `/api/debug/decision-events` SSE 端点
    - 实现 15 秒心跳、客户端断开清理、队列最大容量 100
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
u   - [ ] 7.2 修改 `smartclaw/smartclaw/gateway/routers/sessions.py` 添加 REST API
    - 添加 `GET /{session_key}/decisions` 端点
    - 从 `decision_collector.get_decisions()` 获取记录并返回 JSON 数组
    - session_key 不存在时返回空数组
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 8. 实现 Debug UI 决策时间线标签页
  - [x] 8.1 修改 `smartclaw/smartclaw/gateway/static/index.html`
    - 在 Debug 面板标签栏中，"🪝 Hooks" 之后新增 "🧠 Decisions" 标签页
    - 通过 `EventSource('/api/debug/decision-events')` 接收实时决策事件
    - 按 `decision_type` 使用不同边框色渲染卡片：`tool_call` → 绿色 `#2d4a2d`，`final_answer` → 蓝色 `#2d2d4a`，`supervisor_route` → 紫色 `#4a2d4a`
    - 卡片内容：时间戳、迭代轮次、类型标签、Input Summary、Reasoning（可折叠，默认 3 行）
    - 按时间倒序排列，最多 100 条，无事件时显示"等待决策事件..."
    - 更新 `switchTab` 函数支持 decisions 标签页
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 8.1, 8.2, 8.3, 8.4_

- [x] 9. 最终检查点 — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

## 备注

- 标记 `*` 的任务为可选任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求条款以确保可追溯性
- 检查点确保增量验证
- 属性测试使用 Hypothesis 库，每个属性至少运行 100 次迭代
- 决策捕获逻辑均以 try/except 包裹，确保不影响 Agent 主流程
