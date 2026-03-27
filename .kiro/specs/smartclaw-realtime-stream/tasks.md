# 任务列表：SSE 实时流式展示 Agent 执行全过程

## 任务

- [x] 1. 后端：实现 SSE 实时流式推送机制
  - [x] 1.1 在 `gateway/routers/chat.py` 中实现 `_make_queue_handler()` 工厂函数，创建将 HookEvent 转换为 dict 并写入 asyncio.Queue 的临时 handler（Queue 满时静默丢弃）
  - [x] 1.2 在 `gateway/routers/chat.py` 中实现 `_format_sse()` 映射函数，将 Queue 中的 hook 事件字典转换为 SSE 事件格式（hook_point → event type + data 字段映射）
  - [x] 1.3 在 `gateway/routers/chat.py` 中实现 handler 注册/注销辅助函数 `_register_stream_handlers()` 和 `_unregister_stream_handlers()`，管理 6 个钩子点的临时 handler 生命周期
  - [x] 1.4 重写 `chat_stream()` 的 `event_generator()`：使用 `asyncio.create_task` 并发执行 invoke()，主循环从 Queue 读取事件（1 秒超时），invoke 完成后排空 Queue，最后发送 done/error 事件，finally 块中注销 handler
  - [x] 1.5 实现回退机制：当 Queue/handler 注册异常时，回退到原有的 thinking + done 简单模式
  - [x] 1.6 确保所有 JSON 序列化使用 `ensure_ascii=False`
- [x] 2. 前端：扩展 Debug_UI 事件处理
  - [x] 2.1 修改 `index.html` 的 `handleEvent()` 函数，处理 `thinking` 事件（显示 "⏳ 思考中...（第 N 轮）"，其中 N 来自 data.iteration）
  - [x] 2.2 修改 `handleEvent()` 处理 `tool_call` 事件，增强显示工具名称、参数和 tool_call_id
  - [x] 2.3 修改 `handleEvent()` 处理 `tool_result` 事件，显示结果摘要、耗时（duration_ms）和成功/失败状态
  - [x] 2.4 修改 `handleEvent()` 处理 `iteration` 事件，显示 "🔄 迭代 N/M"
  - [x] 2.5 确保每次收到新事件后自动滚动到底部（已有逻辑，验证覆盖新事件类型）
- [x] 3. 测试：属性测试
  - [x] 3.1 编写 Property 1 属性测试：生成随机 HookEvent，验证 handler 写入 Queue 的完整性和 Queue 满时的丢弃行为
  - [x] 3.2 编写 Property 2 属性测试：生成随机 hook 事件字典，验证 `_format_sse()` 映射的正确性（event 类型 + data 字段）
  - [x] 3.3 编写 Property 3 属性测试：验证临时 handler 注册/注销的完整性和对已有 handler 的隔离性
  - [x] 3.4 编写 Property 4 属性测试：模拟 N 个事件的 invoke 过程，验证 generator yield 的事件数量和最终事件类型
  - [x] 3.5 编写 Property 5 属性测试：生成包含非 ASCII 字符的事件数据，验证 JSON 序列化保留原始字符
  - [x] 3.6 编写 Property 6 属性测试：验证同步端点的向后兼容性
- [x] 4. 测试：单元测试
  - [x] 4.1 编写单元测试覆盖 `_make_queue_handler` 基本行为和 Queue 满场景
  - [x] 4.2 编写单元测试覆盖 `_format_sse` 所有事件类型映射和未知 hook_point 处理
  - [x] 4.3 编写单元测试覆盖 `event_generator` 完整流程（happy path + invoke 异常 + 回退机制）
  - [x] 4.4 编写单元测试验证 handler 在异常/断开时的清理行为
