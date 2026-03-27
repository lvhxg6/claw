# 需求文档：吸收 DeerFlow 四大优势能力

## 简介

当前 SmartClaw 在以下四个方面存在明显不足：(1) Supervisor 提示词过于简单，缺乏决策树、批量规划指导、示例/反例和失败处理策略，导致多 Agent 协调效率低下；(2) 完全没有澄清机制，当 LLM 需要用户补充信息时只能猜测或给出不完整回答；(3) 循环检测仅依赖 `max_iterations` 硬上限，无法在早期识别重复行为模式并及时干预；(4) 系统提示词（`SYSTEM_PROMPT`）过于简略，缺乏结构化的思考指导、工具使用决策树和澄清优先级策略。

本功能从 DeerFlow 开源项目中吸收四大优势能力，对 SmartClaw 进行针对性增强：(1) 增强 Supervisor 提示词与 SpawnSubAgentTool 描述；(2) 新增澄清中断机制（`ask_clarification` 工具）；(3) 新增基于哈希滑动窗口的循环检测；(4) 增强系统提示词。

## 术语表

- **MultiAgentCoordinator**: 多 Agent 协调器，使用 Supervisor 模式编排多个专业 Agent 协作完成任务
- **_SUPERVISOR_SYSTEM_PROMPT**: Supervisor 节点的系统提示词模板，指导 LLM 如何分析任务、选择 Agent 和处理失败
- **SpawnSubAgentTool**: LangChain BaseTool 实现，父 Agent 通过该工具将子任务委派给 Sub-Agent 执行
- **AgentState**: LangGraph StateGraph 的状态 TypedDict，包含消息历史、迭代计数、最终回答等字段
- **ask_clarification**: 新增的澄清工具，LLM 在信息不足时调用该工具向用户提问，中断 Agent 执行循环
- **ClarificationRequest**: 澄清请求数据结构，包含问题文本和可选的选项列表
- **LoopDetector**: 循环检测器，通过哈希滑动窗口算法检测 Agent 是否陷入重复行为模式
- **action_node**: Agent 图的动作节点，负责执行 LLM 返回的工具调用
- **reasoning_node**: Agent 图的推理节点，负责调用 LLM 生成回复或工具调用
- **should_continue**: Agent 图的条件路由函数，决定下一步执行动作节点还是结束
- **SYSTEM_PROMPT**: SmartClaw 的全局系统提示词模板，定义 Agent 的身份、能力和行为准则
- **ToolCallHash**: 工具调用的哈希值，由工具名称和参数的确定性序列化计算得出
- **SlidingWindow**: 滑动窗口，固定大小的队列，用于存储最近 N 次工具调用的哈希值
- **HookEvent**: 钩子事件基类，用于 Agent 生命周期事件的发布/订阅

## 需求

### 需求 1：增强 Supervisor 提示词

**用户故事：** 作为开发者，我希望 Supervisor 的系统提示词包含决策树、批量规划指导、示例/反例和失败处理策略，以提高多 Agent 协调的准确性和鲁棒性。

#### 验收标准

1. THE _SUPERVISOR_SYSTEM_PROMPT SHALL 包含结构化的决策树指导块，明确列出 Supervisor 在以下场景的决策路径：单 Agent 任务直接分配、多步骤任务分解为顺序子任务、并行无依赖任务的批量规划、任务完成后的结果综合
2. THE _SUPERVISOR_SYSTEM_PROMPT SHALL 包含批量规划指导，说明何时将多个独立子任务同时分配给不同 Agent，以及如何在 JSON 响应中表达批量分配（例如返回包含多个 agent 分配的列表）
3. THE _SUPERVISOR_SYSTEM_PROMPT SHALL 包含至少两个正面示例和两个反面示例，展示正确和错误的任务分配决策，每个示例包含用户请求、正确/错误的 JSON 响应和简要解释
4. THE _SUPERVISOR_SYSTEM_PROMPT SHALL 包含失败处理策略块，指导 Supervisor 在以下情况的应对方式：Agent 返回错误时重新分配给其他 Agent、Agent 返回不完整结果时追加补充任务、所有 Agent 均失败时综合已有部分结果并说明失败原因
5. THE _SUPERVISOR_SYSTEM_PROMPT SHALL 保持现有的 JSON 响应格式约定（`{"agent": "<name>"}` 和 `{"agent": "done", "answer": "..."}`），确保 `_parse_supervisor_decision` 方法无需修改
6. THE _SUPERVISOR_SYSTEM_PROMPT 的总长度 SHALL 控制在 3000 个 Token 以内，避免过长的系统提示词占用过多上下文窗口

### 需求 2：增强 SpawnSubAgentTool 描述

**用户故事：** 作为开发者，我希望 SpawnSubAgentTool 的 description 字段包含详细的使用指南，明确何时应该使用和何时不应该使用 Sub-Agent，以减少 LLM 不必要的 Sub-Agent 调用。

#### 验收标准

1. THE SpawnSubAgentTool.description SHALL 包含"何时使用"指南，列出适合委派给 Sub-Agent 的场景：需要独立上下文的复杂子任务、需要不同工具集的专业任务、可并行执行的独立子任务
2. THE SpawnSubAgentTool.description SHALL 包含"何时不使用"指南，列出不应使用 Sub-Agent 的场景：简单的单步工具调用、需要访问当前对话上下文的任务、结果需要与当前对话紧密交互的任务
3. THE SpawnSubAgentTool.description SHALL 包含任务描述编写指南，说明 task 参数应包含：明确的目标、必要的背景信息、期望的输出格式
4. THE SpawnSubAgentTool.description 的总长度 SHALL 控制在 500 个字符以内，在提供足够指导的同时避免过长的工具描述占用上下文

### 需求 3：澄清中断机制

**用户故事：** 作为用户，我希望当 AI 助手信息不足以完成任务时，能够主动向我提问以获取必要信息，而非猜测或给出不完整的回答。

#### 验收标准

1. THE 系统 SHALL 新增 `ask_clarification` LangChain BaseTool，接受 `question`（字符串，向用户提出的问题）和 `options`（可选的字符串列表，预定义的选项供用户选择）两个参数
2. WHEN LLM 调用 `ask_clarification` 工具时，THE action_node SHALL 拦截该工具调用，将澄清请求写入 AgentState 而非执行实际工具逻辑
3. THE AgentState SHALL 新增 `clarification_request` 可选字段（TypedDict），包含 `question`（字符串）和 `options`（可选字符串列表）
4. WHEN AgentState 中存在 `clarification_request` 时，THE should_continue 路由函数 SHALL 返回 "end"，中断 Agent 执行循环
5. THE ChatResponse SHALL 新增可选的 `clarification` 字段，包含 `question` 和 `options`，前端根据该字段展示澄清问题界面
6. WHEN 用户回答澄清问题后，THE chat 端点 SHALL 将用户的回答作为新的 HumanMessage 继续执行 Agent 图，Agent 可基于用户回答继续完成任务
7. THE `ask_clarification` 工具 SHALL 在 `create_system_tools` 中默认注册，使所有 Agent（包括 Sub-Agent）均可使用
8. THE SSE 流式端点 SHALL 在检测到 clarification_request 时发送 `clarification` 事件类型，包含问题和选项数据
9. THE SYSTEM_PROMPT SHALL 包含澄清优先级指导，说明 Agent 在以下情况应优先使用 `ask_clarification`：用户请求模糊且有多种合理解读、缺少执行任务所需的关键参数、操作具有不可逆性（如删除文件）需要用户确认


### 需求 4：基于哈希滑动窗口的循环检测

**用户故事：** 作为开发者，我希望 Agent 能够在早期检测到重复行为模式（如反复调用相同工具和参数），并通过警告注入和强制停止机制避免无效循环消耗资源。

#### 验收标准

1. THE 系统 SHALL 新增 `LoopDetector` 类（新文件 `smartclaw/agent/loop_detector.py`），实现基于哈希滑动窗口的循环检测算法
2. THE LoopDetector SHALL 对每次工具调用计算 ToolCallHash：将工具名称和参数进行确定性 JSON 序列化（`json.dumps` 使用 `sort_keys=True`），然后计算 SHA-256 哈希值的前 16 个十六进制字符
3. THE LoopDetector SHALL 维护一个固定大小的 SlidingWindow（默认容量 20），存储最近 N 次工具调用的 ToolCallHash
4. WHEN 同一 ToolCallHash 在 SlidingWindow 中出现次数达到 `warn_threshold`（默认 3 次）时，THE LoopDetector SHALL 返回 "warn" 状态，action_node 在对应的 ToolMessage 后追加一条系统警告消息，提示 LLM 检测到重复行为并建议尝试不同方法
5. WHEN 同一 ToolCallHash 在 SlidingWindow 中出现次数达到 `stop_threshold`（默认 5 次）时，THE LoopDetector SHALL 返回 "stop" 状态，action_node 将 AgentState 的 error 字段设置为循环检测错误信息，should_continue 路由到 "end" 终止执行
6. THE LoopDetector SHALL 支持通过构造参数配置 `window_size`（滑动窗口大小，默认 20）、`warn_threshold`（警告阈值，默认 3）、`stop_threshold`（强制停止阈值，默认 5）
7. THE action_node SHALL 在执行每个工具调用后，调用 LoopDetector.record 方法记录该调用，并根据返回的状态（"ok"、"warn"、"stop"）执行相应操作
8. THE LoopDetector SHALL 集成到 `build_graph` 函数中，作为可选参数传递给 action_node，未提供时不执行循环检测（向后兼容）

### 需求 5：增强系统提示词

**用户故事：** 作为开发者，我希望 SmartClaw 的系统提示词包含结构化的思考指导、澄清工作流优先级和工具使用决策树，以提高 Agent 的推理质量和行为一致性。

#### 验收标准

1. THE SYSTEM_PROMPT SHALL 包含结构化的思考风格指导块，要求 Agent 在回答前进行分步思考：理解用户意图 → 评估是否需要澄清 → 制定执行计划 → 选择合适工具 → 执行并验证结果
2. THE SYSTEM_PROMPT SHALL 包含澄清工作流优先级指导，明确 Agent 在以下情况应优先调用 `ask_clarification` 而非猜测：用户请求存在歧义、缺少关键执行参数、操作具有破坏性或不可逆性
3. THE SYSTEM_PROMPT SHALL 包含工具使用决策树，以结构化格式（缩进列表）列出每个工具的适用场景和优先级顺序，帮助 LLM 在多个工具可用时做出正确选择
4. THE SYSTEM_PROMPT SHALL 包含错误恢复指导，说明 Agent 在工具调用失败时的标准处理流程：分析错误原因 → 尝试替代方法 → 如果多次失败则向用户说明情况
5. THE SYSTEM_PROMPT 的增强内容 SHALL 以独立的指导块形式追加到现有提示词之后，不修改现有的工具使用说明部分，确保向后兼容
6. THE SYSTEM_PROMPT 的总长度（不含 skills_section 动态部分）SHALL 控制在 2000 个字符以内，在提供充分指导的同时避免过长的系统提示词
