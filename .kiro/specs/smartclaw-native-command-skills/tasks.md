# Implementation Plan: SmartClaw 原生命令技能（Native Command Skills）

## Overview

实现 SmartClaw Skills 系统的原生命令工具扩展（Spec: smartclaw-native-command-skills）。在现有 Python `entry_point` 技能机制基础上，新增三种原生命令工具类型（`shell`、`script`、`exec`），以及 SKILL.md Markdown 提示词型技能支持。

新增文件：`smartclaw/smartclaw/skills/native_command.py`（NativeCommandTool + 占位符替换）、`smartclaw/smartclaw/skills/markdown_skill.py`（SKILL.md 解析器）。修改文件：`smartclaw/smartclaw/skills/models.py`（ParameterDef + ToolDef 扩展）、`smartclaw/smartclaw/skills/loader.py`（YAML 解析扩展 + SKILL.md 发现）、`smartclaw/smartclaw/skills/registry.py`（原生命令工具注册）。测试位于 `smartclaw/tests/skills/`。

实现按依赖顺序推进：ParameterDef + ToolDef 扩展 → SkillDefinition 验证扩展 → 占位符替换 → NativeCommandTool → SkillsLoader YAML 解析扩展 → SKILL.md 解析器 → SkillsLoader 发现扩展 → SkillsRegistry 集成 → 向后兼容验证。

## Tasks

- [x] 1. ParameterDef 与 ToolDef 数据模型扩展
  - [x] 1.1 实现 `ParameterDef` 数据类 (`smartclaw/smartclaw/skills/models.py`)
    - 新增 `ParameterDef` dataclass：type (str, 默认 "string")、description (str, 默认 "")、default (Any, 默认 None)
    - type 支持 `"string"`, `"integer"`, `"boolean"` 三种值
    - default 为 None 表示必填参数
    - _Requirements: 1.10_

  - [x] 1.2 扩展 `ToolDef` 数据类 (`smartclaw/smartclaw/skills/models.py`)
    - 在现有 `ToolDef(name, description, function)` 基础上新增字段：
      - `type: str | None = None` — 工具类型：`"shell"`, `"script"`, `"exec"`, `None`
      - `command: str = ""` — 命令字符串或可执行文件路径
      - `args: list[str] = field(default_factory=list)` — exec 类型的命令行参数列表
      - `working_dir: str | None = None` — 工作目录，支持 `{workspace}` 占位符
      - `timeout: int = 60` — 超时秒数
      - `max_output_chars: int = 10_000` — 输出截断阈值
      - `deny_patterns: list[str] = field(default_factory=list)` — 安全拒绝正则列表
      - `parameters: dict[str, ParameterDef] = field(default_factory=dict)` — 参数定义映射
    - 实现 `ToolDef.validate()` 方法：
      - type 不在 `{"shell", "script", "exec", None}` 中时返回错误
      - type 为 shell/script/exec 且 command 为空时返回错误
      - type 为 None 且 function 为空时返回错误
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.11, 1.12, 1.13_

  - [x] 1.3 扩展 `SkillDefinition.validate()` 验证逻辑 (`smartclaw/smartclaw/skills/models.py`)
    - 当无 `entry_point` 但存在至少一个原生命令工具（type 为 shell/script/exec）时，视为合法
    - 当无 `entry_point` 且无原生命令工具时，返回错误
    - 当同时有 `entry_point` 和原生命令工具时（混合技能），视为合法
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 1.4 编写属性测试：ToolDef 验证 — 原生命令类型必须有 command (`tests/skills/test_models_props.py`)
    - **Property 1: ToolDef 验证 — 原生命令类型必须有 command**
    - 对任意 type 为 "shell"/"script"/"exec" 且 command 为空的 ToolDef，validate() 返回非空错误列表
    - **Validates: Requirements 1.11**

  - [x] 1.5 编写属性测试：ToolDef 验证 — Python 类型必须有 function (`tests/skills/test_models_props.py`)
    - **Property 2: ToolDef 验证 — Python 类型必须有 function**
    - 对任意 type 为 None 且 function 为空的 ToolDef，validate() 返回非空错误列表
    - **Validates: Requirements 1.12**

  - [x] 1.6 编写属性测试：ToolDef 验证 — 无法识别的 type 被拒绝 (`tests/skills/test_models_props.py`)
    - **Property 3: ToolDef 验证 — 无法识别的 type 被拒绝**
    - 对任意 type 不在 `{"shell", "script", "exec", None}` 中的 ToolDef，validate() 返回非空错误列表
    - **Validates: Requirements 1.13**

  - [x] 1.7 编写属性测试：SkillDefinition 验证 — 无 entry_point 但有原生命令工具为合法 (`tests/skills/test_models_props.py`)
    - **Property 12: SkillDefinition 验证 — 无 entry_point 但有原生命令工具为合法**
    - 对任意无 entry_point 但含至少一个 type 为 shell/script/exec 的工具的 SkillDefinition（name/description 合法），validate() 返回空错误列表
    - **Validates: Requirements 9.1**

  - [x] 1.8 编写属性测试：SkillDefinition 验证 — 无 entry_point 且无原生命令工具为非法 (`tests/skills/test_models_props.py`)
    - **Property 13: SkillDefinition 验证 — 无 entry_point 且无原生命令工具为非法**
    - 对任意无 entry_point 且无原生命令工具的 SkillDefinition，validate() 返回非空错误列表
    - **Validates: Requirements 9.2**

  - [x] 1.9 编写单元测试 (`tests/skills/test_models_native.py`)
    - 测试 ParameterDef 各字段默认值正确
    - 测试 ToolDef 各类型合法/非法组合的 validate() 结果
    - 测试 SkillDefinition 混合工具（entry_point + 原生命令）验证通过
    - 测试 SkillDefinition 纯原生命令（无 entry_point）验证通过
    - _Requirements: 1.1, 1.10, 1.11, 1.12, 1.13, 9.1, 9.2, 9.3_

- [x] 2. Checkpoint — 确认数据模型扩展测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. 占位符替换模块
  - [x] 3.1 实现占位符替换函数 (`smartclaw/smartclaw/skills/native_command.py`)
    - 实现 `substitute_placeholders(template, params, param_defs)` 函数：
      - 使用 `re.findall(r'\{(\w+)\}', template)` 提取占位符名称
      - 参数在 params 中 → 使用 `str(params[name])`
      - 参数不在 params 中但在 param_defs 中有默认值 → 使用默认值
      - 参数不在 params 中且无默认值 → 抛出 `ValueError("Missing required parameter: {name}")`
      - 非字符串值通过 `str()` 转换
    - 实现 `substitute_args(args, params, param_defs)` 函数：对 args 列表每个元素调用 substitute_placeholders
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6_

  - [x] 3.2 编写属性测试：占位符替换完整性 (`tests/skills/test_native_command_props.py`)
    - **Property 5: 占位符替换完整性**
    - 对任意包含 N 个不同 `{param_name}` 占位符的模板字符串和提供所有 N 个参数值的 params dict，substitute_placeholders() 返回的字符串不包含这 N 个占位符，且每个占位符被替换为对应参数值的字符串表示
    - **Validates: Requirements 3.1, 3.2, 3.6**

  - [x] 3.3 编写属性测试：缺失必填参数报错 (`tests/skills/test_native_command_props.py`)
    - **Property 6: 缺失必填参数报错**
    - 对任意包含 `{param_name}` 占位符的模板字符串，当 param_name 不在 params dict 中且在 param_defs 中无默认值时，substitute_placeholders() 抛出 ValueError
    - **Validates: Requirements 3.5**

  - [x] 3.4 编写属性测试：默认值回退 (`tests/skills/test_native_command_props.py`)
    - **Property 7: 默认值回退**
    - 对任意包含 `{param_name}` 占位符的模板字符串，当 param_name 不在 params dict 中但在 param_defs 中有默认值时，substitute_placeholders() 使用默认值替换
    - **Validates: Requirements 3.4**

  - [x] 3.5 编写单元测试 (`tests/skills/test_placeholder.py`)
    - 测试多参数替换 happy path
    - 测试默认值回退
    - 测试缺失必填参数抛出 ValueError
    - 测试非字符串值（int、bool）转换为字符串
    - 测试 `{workspace}` 特殊占位符处理
    - 测试 substitute_args 对列表每个元素替换
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 4. NativeCommandTool 实现
  - [x] 4.1 实现动态 args_schema 生成 (`smartclaw/smartclaw/skills/native_command.py`)
    - 实现 `_build_args_schema(tool_name, param_defs)` 函数：
      - 使用 `pydantic.create_model()` 动态创建 BaseModel 子类
      - 类型映射：`"string"` → `str`、`"integer"` → `int`、`"boolean"` → `bool`、其他 → `str`
      - default 为 None 的参数为必填字段（无默认值）
      - default 有值的参数使用 `Field(default=...)`
      - 模型名称为 `{ToolName}Input`（驼峰化）
    - _Requirements: 7.4, 1.10_

  - [x] 4.2 实现 `NativeCommandTool` 类 (`smartclaw/smartclaw/skills/native_command.py`)
    - 继承 `SmartClawTool`，包含内部配置字段：tool_type, command, command_args, working_dir, timeout, max_output_chars, deny_patterns, param_defs
    - 实现 `_arun(**kwargs)` 执行流程：
      1. 占位符替换（command + args + working_dir）
      2. deny_patterns 正则检查（替换后的完整命令）
      3. working_dir 存在性检查
      4. 根据 tool_type 选择执行方式：
         - shell → `create_subprocess_shell(command)`
         - script → `create_subprocess_shell(command + args)`
         - exec → `create_subprocess_exec(command, *args)`
      5. `asyncio.wait_for` 超时控制，超时时 kill 进程
      6. 组装输出：stdout + stderr（STDERR: 前缀）+ 非零退出码
      7. 输出截断：超过 max_output_chars 时截断并追加截断指示
    - 使用 `_safe_run` 包装所有执行
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [x] 4.3 实现 `NativeCommandTool.from_tool_def()` 工厂方法 (`smartclaw/smartclaw/skills/native_command.py`)
    - 接受 ToolDef，验证 type 为 shell/script/exec
    - 调用 `_build_args_schema` 生成动态 args_schema
    - 返回配置完整的 NativeCommandTool 实例
    - type 不支持时抛出 `ValueError("Unsupported tool type: {type}")`
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6_

  - [x] 4.4 编写属性测试：Deny pattern 阻止匹配命令 (`tests/skills/test_native_command_props.py`)
    - **Property 8: Deny pattern 阻止匹配命令**
    - 对任意命令字符串和 deny_patterns 列表，若命令匹配任一 deny pattern 正则，NativeCommandTool 返回安全策略错误字符串
    - **Validates: Requirements 4.7, 5.7, 6.7**

  - [x] 4.5 编写属性测试：输出截断保持长度限制 (`tests/skills/test_native_command_props.py`)
    - **Property 9: 输出截断保持长度限制**
    - 对任意超过 max_output_chars 的子进程输出，返回字符串长度 ≤ max_output_chars + 截断指示长度，且以截断指示结尾
    - **Validates: Requirements 4.6, 5.6, 6.6**

  - [x] 4.6 编写属性测试：工厂创建的 BaseTool 属性正确 (`tests/skills/test_native_command_props.py`)
    - **Property 10: 工厂创建的 BaseTool 属性正确**
    - 对任意 type 为 shell/script/exec 的合法 ToolDef，`NativeCommandTool.from_tool_def()` 返回的 BaseTool 实例 name 等于 tool_def.name、description 等于 tool_def.description、args_schema 为 Pydantic BaseModel 子类且字段匹配 parameters
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

  - [x] 4.7 编写属性测试：动态 args_schema 类型映射 (`tests/skills/test_native_command_props.py`)
    - **Property 11: 动态 args_schema 类型映射**
    - 对任意 ParameterDef dict，动态生成的 args_schema 将 "string" 映射为 str、"integer" 映射为 int、"boolean" 映射为 bool，default=None 的参数为必填字段
    - **Validates: Requirements 7.4, 1.10**

  - [x] 4.8 编写单元测试 (`tests/skills/test_native_command.py`)
    - 测试 shell 类型 happy path：echo 命令执行并返回输出
    - 测试 script 类型 happy path：脚本执行并传递参数
    - 测试 exec 类型 happy path：程序执行并传递 args 列表
    - 测试超时 kill 进程并返回超时错误
    - 测试输出截断并追加截断指示
    - 测试 deny pattern 阻止命令并返回安全策略错误
    - 测试 working_dir 不存在返回目录错误
    - 测试非零退出码包含在输出中
    - 测试工厂方法不支持的 type 抛出 ValueError
    - 使用 AsyncMock mock asyncio subprocess 避免真实子进程
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.1, 5.5, 5.9, 6.1, 6.9, 7.5, 7.6_

- [x] 5. Checkpoint — 确认占位符替换与 NativeCommandTool 测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. SkillsLoader YAML 解析扩展
  - [x] 6.1 扩展 `parse_skill_yaml()` 解析原生命令工具字段 (`smartclaw/smartclaw/skills/loader.py`)
    - 解析 tool entry 中的 `type`、`command`、`args`、`working_dir`、`timeout`、`max_output_chars`、`deny_patterns` 字段
    - 解析 `parameters` 字段为 `dict[str, ParameterDef]` 对象
    - 未指定 `type` 时 ToolDef.type 为 None，保持向后兼容
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 6.2 扩展 `serialize_skill_yaml()` 序列化原生命令字段 (`smartclaw/smartclaw/skills/loader.py`)
    - 序列化时包含 type、command、args、working_dir、timeout、max_output_chars、deny_patterns、parameters 字段
    - 仅序列化非默认值字段（type 为 None 时不输出、args 为空列表时不输出等）
    - _Requirements: 2.6_

  - [x] 6.3 编写属性测试：SkillDefinition YAML 往返一致性（含原生命令工具）(`tests/skills/test_loader_native_props.py`)
    - **Property 4: SkillDefinition YAML 往返一致性（含原生命令工具）**
    - 对任意包含原生命令工具的合法 SkillDefinition，serialize_skill_yaml 后 parse_skill_yaml 返回等价 SkillDefinition，所有字段保留
    - **Validates: Requirements 2.7**

  - [x] 6.4 编写属性测试：向后兼容 — 无 type 字段的 ToolDef 解析不变 (`tests/skills/test_loader_native_props.py`)
    - **Property 14: 向后兼容 — 无 type 字段的 ToolDef 解析不变**
    - 对任意不包含 type 字段的 skill.yaml 工具定义，parse_skill_yaml() 解析结果中 ToolDef.type 为 None，function 字段正确填充
    - **Validates: Requirements 2.2, 10.2, 10.3**

  - [x] 6.5 编写单元测试 (`tests/skills/test_loader_native.py`)
    - 测试原生命令工具 YAML 解析 happy path（shell/script/exec 三种类型）
    - 测试 parameters 字段解析为 ParameterDef 对象
    - 测试序列化后再解析的往返一致性
    - 测试无 type 字段的传统工具解析不受影响（向后兼容）
    - 测试现有 skill.yaml 文件解析结果与扩展前一致
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 10.2, 10.3_

- [x] 7. Checkpoint — 确认 SkillsLoader YAML 解析扩展测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. SKILL.md 解析器与 SkillsLoader 发现扩展
  - [x] 8.1 实现 SKILL.md 解析器 (`smartclaw/smartclaw/skills/markdown_skill.py`)
    - 实现 `split_frontmatter(content)` 函数：
      - 分离 YAML frontmatter（`---` 分隔符之间的内容）和 Markdown body
      - 无 frontmatter（无 `---` 开头）时返回 `("", content)`
    - 实现 `parse_skill_md(content, dir_name)` 函数：
      - 从 frontmatter 提取 name 和 description
      - name 缺失时使用 dir_name 作为回退
      - description 缺失时使用 Markdown body 第一段落作为回退
      - 返回 `(name, description, body)`，body 为去除 frontmatter 后的 Markdown 内容
    - 无效 YAML frontmatter 时回退到目录名和第一段落
    - _Requirements: 11.2, 11.3, 11.4, 11.10, 11.11_

  - [x] 8.2 扩展 `SkillsLoader.list_skills()` 支持 SKILL.md 发现 (`smartclaw/smartclaw/skills/loader.py`)
    - 提取 `_scan_skill_dir(child, source)` 内部方法，统一扫描逻辑
    - 扫描时同时检查 `skill.yaml` 和 `SKILL.md`
    - skill.yaml 存在 → 解析 YAML 获取元数据
    - SKILL.md 存在 → 解析 frontmatter 获取元数据
    - 两者都存在 → 混合技能（YAML 提供工具，MD 提供提示词）
    - 两者都不存在 → 非有效技能目录，跳过
    - _Requirements: 11.1, 11.5, 11.6, 12.1, 12.2_

  - [x] 8.3 扩展 `SkillsLoader.load_skill()` 支持 SKILL.md 加载 (`smartclaw/smartclaw/skills/loader.py`)
    - 当技能有 SKILL.md 时，返回 body 内容
    - 纯 MD 技能（无 skill.yaml）作为提示词技能加载
    - _Requirements: 11.7_

  - [x] 8.4 扩展 `SkillsLoader.build_skills_summary()` 和 `load_skills_for_context()` (`smartclaw/smartclaw/skills/loader.py`)
    - build_skills_summary 包含 Markdown 技能的 name 和 description
    - load_skills_for_context 加载 SKILL.md 内容并拼接
    - _Requirements: 11.8, 11.9_

  - [x] 8.5 编写属性测试：SKILL.md frontmatter 解析 — name 和 description 提取 (`tests/skills/test_markdown_skill_props.py`)
    - **Property 15: SKILL.md frontmatter 解析 — name 和 description 提取**
    - 对任意包含有效 YAML frontmatter 的 SKILL.md 内容，parse_skill_md() 正确提取 name 和 description，body 不包含 frontmatter
    - **Validates: Requirements 11.2, 11.4**

  - [x] 8.6 编写属性测试：SKILL.md 无 frontmatter 回退 (`tests/skills/test_markdown_skill_props.py`)
    - **Property 16: SKILL.md 无 frontmatter 回退**
    - 对任意不包含 YAML frontmatter 的 SKILL.md 内容，parse_skill_md() 使用目录名作为 name，第一段落作为 description，body 为完整内容
    - **Validates: Requirements 11.3**

  - [x] 8.7 编写属性测试：技能目录发现 — skill.yaml 或 SKILL.md 均为有效技能 (`tests/skills/test_markdown_skill_props.py`)
    - **Property 17: 技能目录发现 — skill.yaml 或 SKILL.md 均为有效技能**
    - 对任意包含 skill.yaml 或 SKILL.md（或两者）的技能目录，list_skills() 将其识别为有效技能；不包含任何一个的目录被忽略
    - **Validates: Requirements 12.1, 12.2**

  - [x] 8.8 编写单元测试 (`tests/skills/test_markdown_skill.py`)
    - 测试 frontmatter 解析 happy path：提取 name、description、body
    - 测试无 frontmatter 回退：目录名作为 name，第一段落作为 description
    - 测试无效 frontmatter 容错：回退到目录名和第一段落
    - 测试混合技能目录发现：skill.yaml + SKILL.md
    - 测试纯 MD 技能加载：无 skill.yaml 的 SKILL.md 技能
    - 测试 build_skills_summary 包含 MD 技能
    - 测试 load_skills_for_context 加载 SKILL.md 内容
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.11, 12.1, 12.2_

- [x] 9. Checkpoint — 确认 SKILL.md 解析器与发现扩展测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. SkillsRegistry 集成与向后兼容验证
  - [x] 10.1 扩展 `SkillsRegistry.load_and_register_all()` 支持原生命令工具注册 (`smartclaw/smartclaw/skills/registry.py`)
    - 遍历 SkillDefinition.tools，对 type 为 shell/script/exec 的 ToolDef 调用 `NativeCommandTool.from_tool_def()` 创建 BaseTool 并注册到 ToolRegistry
    - 对 type 为 None 的工具保持现有 Python entry_point 加载机制
    - 混合技能（entry_point + 原生命令工具）两种类型都注册
    - 纯 YAML 技能（无 entry_point，仅原生命令工具）正确注册
    - 单个原生命令工具注册失败时 structlog 记录错误，继续注册其余工具
    - ToolDef 验证失败时 structlog 记录错误，跳过该工具
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 10.2 向后兼容验证
    - 确认现有 Python entry_point 技能加载机制完全不变
    - 确认现有 skill.yaml 文件（无 type 字段）解析和加载结果与扩展前一致
    - 确认 SkillsLoader parse_skill_yaml / serialize_skill_yaml 对传统 skill.yaml 产生相同结果
    - 确认 SkillsRegistry load_and_register_all 同时处理 Python entry_point 和原生命令技能
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 10.3 编写单元测试 (`tests/skills/test_registry_native.py`)
    - 测试原生命令工具注册 happy path：shell/script/exec 三种类型工具注册到 ToolRegistry
    - 测试混合技能注册：entry_point 工具 + 原生命令工具同时注册
    - 测试纯 YAML 技能（无 entry_point）注册成功
    - 测试单个原生命令工具注册失败时继续注册其余工具
    - 测试 ToolDef 验证失败时跳过该工具
    - 测试向后兼容：传统 Python entry_point 技能注册行为不变
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3, 10.4_

- [x] 11. Final checkpoint — 确认全部测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- 每个属性测试必须运行至少 100 次迭代 (`@settings(max_examples=100, deadline=None)`)
- 每个属性测试必须包含注释标注：`# Feature: smartclaw-native-command-skills, Property {N}: {title}`
- 属性测试使用 Hypothesis 库（已在 dev 依赖中：`hypothesis>=6.98.0`）
- 命令执行测试使用 `AsyncMock` mock `asyncio.create_subprocess_shell/exec` 避免真实子进程
- 单元测试使用 `pytest-asyncio` 支持异步测试
- 所有 12 个需求（Requirements 1–12）均被实现和测试任务覆盖
- 所有 17 个正确性属性（Properties 1–17）均有对应的属性测试任务
- 实现按依赖顺序推进，每个主要模块后设置 checkpoint 确保增量验证
- Python 为实现语言（与设计文档一致）
- 技能目录优先级保持不变：workspace > global > builtin
