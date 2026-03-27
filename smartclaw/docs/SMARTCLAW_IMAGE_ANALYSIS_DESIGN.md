# SmartClaw 图片识别与分析设计

## 1. 目标

为 `smartclaw` 增加图片上传后的识别与分析能力，但不把“图片支持”简单等同于“多模态模型支持”。

目标拆成两层：

- 第一层：让图片像文档附件一样，能被上传、会话关联、产生可消费的分析结果
- 第二层：根据模型能力自动选择
  - 多模态直连
  - 非多模态降级

这次设计的重点不是只做某一个图片模型适配，而是给 SmartClaw 建一套长期可扩展的图片分析机制。

---

## 2. 当前现状

### 2.1 已有能力

当前系统已经具备两块基础能力：

- 图片上传链路已经存在，图片会被当作附件存储并绑定到会话
- Agent 内部已经有多模态消息构造函数 `create_vision_message()`，可生成 `text + image_url(data URI)` 的 `HumanMessage`

相关代码：

- [image_stub.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/uploads/extractors/image_stub.py)
- [graph.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/graph.py#L452)

### 2.2 当前缺口

当前图片上传后，系统只返回一个占位结果：

- “图片已上传，但当前链路未启用图片理解能力”

也就是说现在有：

- 上传
- 存储
- 会话绑定
- 前端附件显示

但没有：

- OCR
- 图片描述
- 截图理解
- 表格图片理解
- 多模态直连调度

### 2.3 当前主链语义

当前 `chat` 主链依赖附件文本化结果：

- 上传后提取 `extract_text / extract_summary`
- `/api/chat` 接收 `attachment_ids`
- `chat` 路由把附件摘要拼进请求文本上下文

这条链对文档很合适，但对图片不够，因为图片未必能天然转成文本。

---

## 3. 核心结论

**图片识别必须区分多模态模型与非多模态模型。**

原因不是产品策略，而是技术输入格式完全不同：

- 多模态模型能直接消费图片块
- 非多模态模型只能消费文本

因此 SmartClaw 应该有两条图片处理路径：

1. `vision` 路径
   直接把图片传给支持图片输入的模型

2. `textified-image` 路径
   先把图片转成文本结果，再交给普通模型

最终两条路径都应沉淀成统一的附件分析结果，方便会话复用与后续编排。

---

## 4. 推荐总架构

建议增加一个统一概念：

- `Image Analysis Pipeline`

它位于当前上传体系之上，负责按策略分发到不同图片处理方式。

总体结构：

1. `Upload API`
2. `Attachment Store`
3. `Image Analysis Policy`
4. `Vision Adapter` 或 `OCR / CV Adapter`
5. `Attachment Result Store`
6. `Chat / Orchestrator Consumption`

也就是说：

- 上传层不关心模型
- 图片分析策略层决定用哪条能力链
- 最终都产出结构化结果

---

## 5. 两条执行路径

## 5.1 路径 A：多模态模型直连

适用前提：

- 当前选中的模型支持视觉输入
- 请求或能力包允许使用 `vision`

流程：

1. 用户上传图片
2. 系统读取图片 bytes
3. Base64 编码
4. 用 `create_vision_message()` 构造消息
5. 调用多模态模型
6. 保存分析结果到附件记录
7. 将摘要结果回填到页面和会话上下文

优点：

- 能力最强
- 对截图、图表、复杂页面更有效
- 不需要先做 OCR 才能回答“这图里是什么”

缺点：

- 强依赖模型能力
- 成本更高
- 各模型支持格式不完全一致

## 5.2 路径 B：非多模态文本化降级

适用前提：

- 当前模型不支持视觉输入
- 或策略要求走文本化分析

流程：

1. 用户上传图片
2. 系统提取图片基础元数据
3. 执行 OCR / 图像解析
4. 生成文本结果
5. 写入 `extract_text / extract_summary`
6. 继续走当前附件文本注入链

优点：

- 与现有文档上传分析架构最一致
- 对模型无要求
- 对 capability pack / orchestrator 改动最小

缺点：

- 对复杂视觉推理支持有限
- 图像语义理解能力弱于真正的多模态模型

---

## 6. 为什么不能只做多模态

如果直接把“图片支持”设计成“必须 vision 模型”，会有几个问题：

- 当前很多场景可能仍然用普通文本模型
- 同一业务包可能会切不同模型
- OCR 场景和扫描件场景本质上更适合先文本化
- 后续 capability pack 很难统一治理

所以 SmartClaw 更合适的产品语义不是：

- “有没有多模态”

而是：

- “图片分析策略是什么”

---

## 7. 推荐策略模型

建议增加一个配置项：

- `image_analysis_mode`

支持值：

- `disabled`
- `ocr_only`
- `vision_preferred`
- `vision_only`

行为定义：

### 7.1 `disabled`

图片可上传，但不做识别。

适用：

- 仅做附件归档
- 上传能力先上线，识别能力后补

### 7.2 `ocr_only`

无论当前模型是否支持 vision，都先走 OCR / 文本化链。

适用：

- 当前阶段只想做非多模态支持
- 更关注扫描件、截图文字、票据类图片

### 7.3 `vision_preferred`

如果模型支持图片输入，则优先 vision；否则自动回退 OCR。

适用：

- 未来推荐默认模式
- 同时兼容高能力模型与普通模型

### 7.4 `vision_only`

只允许支持图片输入的模型处理图片；不支持时直接报错。

适用：

- 对视觉理解质量要求非常高
- 不接受 OCR 降级

---

## 8. 模型能力判定设计

当前代码里没有现成的 `supports_vision` 能力注册表，因此建议新增一层：

- `ModelCapabilityRegistry`

目标：

- 不把“vision 支持”写死在业务逻辑里
- 不把某个 provider 的特殊规则散落在前端和路由中

建议接口：

```python
class ModelCapabilities(BaseModel):
    supports_vision: bool = False
    supports_streaming: bool = True
    supports_tool_calling: bool = True
```

建议暴露一个查询函数：

```python
def resolve_model_capabilities(model_name: str, provider: str | None = None) -> ModelCapabilities:
    ...
```

能力来源优先级建议：

1. provider 配置显式声明
2. model alias registry
3. capability pack 强制覆盖
4. 默认保守值

第一版不必做动态探测，先做配置驱动即可。

### 8.1 当前系统状态

这一点需要说清楚：

- **当前已经落地的图片能力是 OCR**
- 因此 **当前运行中的 SmartClaw 并不会判断模型是不是多模态**
- 现在图片识别链路和模型能力是解耦的

也就是说，当前系统的真实行为是：

1. 图片上传
2. OCR 提取文本
3. 把 OCR 结果写回附件
4. 再像文档一样交给普通聊天链分析

所以：

- 现在不是“先试 vision，失败再回退”
- 现在也不是“先判断模型是不是多模态再决定能不能识别图片”
- 当前图片能力本质上是 **模型无关的 OCR 附件分析**

### 8.2 未来为什么不能默认“先试一下，失败再兜底”

如果以后接入真正的多模态 vision 分析，不建议把判定逻辑设计成：

- 先往模型里塞图片
- 如果失败就认定它不是多模态

原因是“失败”并不等于“不支持 vision”。

失败可能来自：

- provider 网络错误
- API key / 权限错误
- 请求格式错误
- 模型名写错
- provider 临时故障
- 附件大小超限
- 图片编码格式不兼容

如果把这些都解释成“这个模型不是多模态”，系统会产生错误路由。

因此推荐原则是：

- **优先显式能力判断**
- **失败分类只作为受控 fallback 的辅助信号**

### 8.3 推荐的能力来源优先级

未来在 `vision_preferred / vision_only` 模式下，能力判断顺序建议固定为：

1. **请求显式覆盖**
   例如调试或灰度场景手工指定：
   - `supports_vision=true`
   - `supports_vision=false`

2. **Capability Pack 覆盖**
   某个业务包可以要求：
   - 强制 OCR
   - 强制 vision
   - 只允许特定模型族使用图片直读

3. **Provider / Model 配置声明**
   在 provider registry 或 model registry 中显式标注：
   - `supports_vision`
   - `supports_tool_calling`
   - `supports_streaming`

4. **模型别名注册表**
   对已知模型做内建映射。

5. **默认保守值**
   未知模型按：
   - `supports_vision = false`

这意味着：

- 默认不靠试错推断
- 默认不把未知模型当成 vision

### 8.4 推荐的数据结构

建议把能力模型补得更完整一点，而不是只放一个布尔值：

```python
class ModelCapabilities(BaseModel):
    supports_vision: bool = False
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_json_mode: bool = False
    max_image_count: int | None = None
    max_image_bytes: int | None = None
```

对应查询接口建议是：

```python
def resolve_model_capabilities(
    provider: str,
    model: str,
    *,
    capability_pack: str | None = None,
    request_overrides: dict | None = None,
) -> ModelCapabilities:
    ...
```

### 8.5 `vision_preferred` 的正确路由语义

这个模式最容易写错，因此建议把规则写死：

1. 先查 `supports_vision`
2. 如果为 `true`
   - 进入 vision 路径
3. 如果为 `false`
   - 进入 OCR 路径
4. 如果能力未知
   - 默认进入 OCR 路径
   - 可选记录一个诊断事件：`vision.capability_unknown`

也就是说：

- `vision_preferred` 不是“先试 vision 再说”
- 而是“**先查能力，能力成立才走 vision**”

### 8.6 什么情况下允许试探性 fallback

只有一种情况建议允许“先试一下”：

- 你明确把模型标记成 `supports_vision=true`
- 但 provider 返回的是**可识别的能力不支持错误**

例如：

- `image input not supported`
- `unsupported content type: image_url`
- `vision not enabled for this model`

这时可以做一次受控 fallback：

1. 记录诊断事件：
   - `vision.request_rejected`
2. 本次请求自动回退到 OCR
3. 不自动修改全局能力注册表
4. 但可以把该 provider/model 记入短期冷却缓存，避免同会话反复撞墙

关键点：

- 这里只对**明确的能力拒绝错误**做 fallback
- 对网络错误、超时、鉴权错误，不应改走 OCR 并误判为“不是 vision 模型”

### 8.7 推荐的错误分类

为了让 fallback 可控，vision 调用错误至少要分 4 类：

1. **Capability Rejection**
   例如模型明确说不支持图片输入

2. **Request Formatting Error**
   例如消息块格式不合法

3. **Transport / Provider Error**
   例如超时、5xx、连接错误

4. **Policy Error**
   例如 capability pack 禁止 vision

只有第一类适合自动退回 OCR。

### 8.8 对开发实现的直接建议

真正开始开发 `vision_preferred` 时，先做这三件事：

1. 在 provider/model 层增加 `supports_vision`
2. 增加 `resolve_model_capabilities()`
3. 在图片请求路由里做显式能力分流

不要一开始就写成：

```python
try:
    run_vision()
except Exception:
    run_ocr()
```

这种写法短期看省事，长期会把网络错误、权限错误、格式错误和能力判断混在一起，后面几乎不可维护。

### 8.9 当前实现进度

截至当前代码状态，下面这部分已经落地：

- `ProviderSpec.supports_vision`
- `ProviderSpec.model_capabilities`
- `ModelCapabilities`
- `resolve_model_capabilities()`
- `AgentRuntime.resolve_model_capabilities()`
- `image_analysis_mode = disabled | ocr_only | vision_preferred | vision_only`
- `/api/chat` 图片附件分流
- `/api/chat/stream` 图片附件分流
- `vision_preferred` 基于 `supports_vision` 的显式判断
- `vision_only` 的能力拒绝错误返回
- 非 vision 模型下的 OCR 文本回退路径
- 内置默认能力表已补充：
  - `glm/glm-5 -> supports_vision=false`
  - `kimi/kimi-k2.5 -> supports_vision=true`

也就是说：

- **模型能力注册与解析骨架已经有了**
- **聊天主链已经接入 `vision_preferred / vision_only`**

当前仍然是：

- OCR 仍然是默认与保守主路径
- Vision 已经是按能力可选路径
- 还没有做“vision 调用失败后基于错误分类再细分重试/降级”
- 还没有做 capability pack 级图片策略覆盖

---

## 9. 附件数据模型扩展

当前附件记录主要有：

- `extract_text`
- `extract_summary`
- `extract_status`
- `error_message`

为了支持图片分析，建议扩展：

- `analysis_mode`
  - `none`
  - `ocr`
  - `vision`
- `analysis_status`
  - `pending`
  - `success`
  - `unsupported`
  - `failed`
- `analysis_text`
- `analysis_summary`
- `analysis_confidence`
- `analysis_meta`
  - JSON 字段
  - 保存尺寸、OCR 行数、模型名、页内区域信息等

建议保留现有 `extract_*` 字段不删：

- 文档类继续用 `extract_*`
- 图片类可先复用 `extract_*`
- 长期再逐步迁移到更清晰的 `analysis_*`

第一版为了兼容，可以采用：

- 图片分析结果同时写入 `extract_text / extract_summary`
- 再额外写一份 `analysis_mode`

---

## 10. 推荐模块拆分

建议新增以下模块：

### 10.1 上传提取器层

- `smartclaw/uploads/extractors/image_analysis.py`
  负责图片分析策略总入口

- `smartclaw/uploads/extractors/ocr_image.py`
  负责 OCR / 文本化图片解析

- `smartclaw/uploads/extractors/vision_image.py`
  负责多模态图片分析

### 10.2 能力注册层

- `smartclaw/providers/capabilities.py`
  负责模型能力查询

### 10.3 图片工具层

- `smartclaw/uploads/image_utils.py`
  负责：
  - base64
  - 图片尺寸
  - MIME/格式检查
  - 压缩/缩放

### 10.4 可选 OCR 适配层

- `smartclaw/uploads/ocr_adapters/`
  第一版可以只做一个实现

---

## 11. 多模态直连如何接到现有链路

当前多模态能力入口是 [create_vision_message](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/graph.py#L452)。

但现有 `invoke()` 入口主要接收文本消息，因此直接接 vision 需要两种方案：

### 方案 A：上传时预分析

上传图片后，立刻用多模态模型做一次分析，把结果写成摘要。

后续聊天时仍然只用文本摘要。

优点：

- 不改当前主 `invoke()` 合同
- 与现有附件上下文模式最一致

缺点：

- 上传时就消耗模型调用
- 用户若没有立刻问图片，可能有浪费

### 方案 B：聊天时按需分析

当请求引用图片附件时，如果当前模型支持 vision，则即时构造 vision message。

优点：

- 只在真正需要时调用多模态
- 能结合当前问题上下文分析图片

缺点：

- 需要改 `chat -> invoke` 输入结构
- 流式链路和普通链路都要补

### 结论

第一版建议：

- **上传阶段只做元数据和可选 OCR**
- **聊天阶段按需进行 vision 分析**

这样成本更合理，也更符合用户问题上下文。

---

## 12. 非多模态 OCR 路线如何接入

这条路与现有系统最兼容。

建议流程：

1. 上传图片
2. 调 `OcrImageExtractor`
3. 得到：
   - `text`
   - `summary`
   - `supported`
   - `error`
4. 写入附件记录
5. `/api/chat` 拼接到附件上下文

这意味着图片在非多模态模型下会表现得像：

- “一个特殊的文档附件”

这是当前系统最稳定的设计。

---

## 13. 前端交互建议

前端不应该把“是否 vision”暴露给用户做复杂判断，而应通过更直观的提示展示。

建议在附件卡片上增加：

- 图片类型标签
- 分析模式
  - `OCR`
  - `Vision`
  - `未分析`
- 识别状态
- 识别摘要

如果当前模型不支持 vision，而用户上传了图片，可以提示：

- `当前模型不支持图片直读，已尝试按 OCR 文本解析`

如果当前模型支持 vision，则在发送时显示：

- `本次将使用图片理解能力`

---

## 14. 与 capability pack 的关系

图片识别不应只挂在全局配置上，也应支持 capability pack 约束。

能力包里建议增加：

- `image_analysis_mode`
- `allow_vision`
- `allow_ocr`
- `max_images_per_request`
- `image_types`
  - `screenshot`
  - `scan`
  - `chart`
  - `photo`

例子：

### `scan-ocr`

- `image_analysis_mode=ocr_only`

适合：

- 扫描件
- 文档拍照
- 票据截图

### `screenshot-analysis`

- `image_analysis_mode=vision_preferred`

适合：

- Web 页面截图
- 系统告警截图
- 控制台界面截图

### `chart-summary`

- `image_analysis_mode=vision_only`

适合：

- 图表理解
- 趋势分析
- 可视化面板解释

---

## 15. 编排层如何用

图片识别接入后，orchestrator 可以把它当成一个阶段或子任务。

典型模式：

1. 收集附件
2. 判断图片类型
3. 走 OCR 或 vision
4. 产出结构化摘要
5. 与文档/表格结果合并分析

例如：

- 子任务 1：OCR 扫描件
- 子任务 2：解析上传的 Excel
- 子任务 3：对截图执行界面分析
- 子任务 4：综合形成报告

也就是说，图片分析本身可以是一个 `subagent` 任务，但它不应该被设计成“每张图都直接塞给主链猜”。

---

## 16. 推荐落地顺序

### Phase 1：OCR 优先

先做：

- 图片元数据提取
- OCR 适配
- 结果写入附件记录
- 页面显示 OCR 结果

这版不要求多模态模型。

### Phase 2：Vision 按需接入

再做：

- `ModelCapabilityRegistry`
- `vision_preferred / vision_only`
- 聊天阶段按需图片分析
- 结果回写附件记录

### Phase 3：复杂图片类型增强

最后再做：

- 图表理解
- UI 截图理解
- 多图比较
- 区域级分析

---

## 17. 第一版建议选型

如果现在开始做，我建议：

### 17.1 第一优先

- 先做 `ocr_only`
- 不急着改主 `invoke()` 消息模型
- 让图片像文档一样先“可文本化消费”

### 17.2 第二优先

- 再接 `vision_preferred`
- 先支持少数已知可用模型

### 17.3 暂不建议

- 一上来就把所有图片请求都改成多模态消息
- 让前端去强行判断模型能不能看图
- 在 capability pack 之前把图片策略写死

---

## 18. 风险与边界

### 18.1 OCR 风险

- 准确率依赖图片质量
- 表格和复杂版面不稳定
- 扫描件可能需要额外预处理

### 18.2 Vision 风险

- 模型能力不稳定
- 成本较高
- 不同 provider 输入格式可能不同

### 18.3 当前系统边界

如果不改 `chat -> invoke` 结构，vision 直连最好先走“聊天阶段的旁路分析”，不要硬改主消息链。

这意味着第一版更推荐：

- OCR 先落
- vision 先以旁路分析器形式接入

---

## 19. 最终建议

对 SmartClaw 来说，正确的图片支持架构不是：

- “图片上传 = 多模态”

而应该是：

- “图片上传 = 统一附件资源”
- “图片分析 = 按策略选择 OCR 或 vision”
- “最终结果 = 统一沉淀成附件分析结果”

一句话总结：

**一定要区分多模态与非多模态模型。**

最稳的落地顺序是：

1. 先做 `ocr_only`
2. 再做 `vision_preferred`
3. 最后做复杂图片理解

这样既不破坏现在的上传分析架构，也能自然演进到真正的多模态能力。
