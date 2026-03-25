# Requirements Document

## Introduction

SmartClaw 已有的 Skills 系统（P1 阶段实现）支持通过 `skill.yaml` 定义技能，使用 `entry_point` 指向 Python 模块来提供 LangChain BaseTool 实例。当前的限制是：所有技能工具必须通过 Python `entry_point` 函数提供，用户若想执行 shell 命令、脚本或外部编译程序（如 Go 二进制），必须编写 Python 包装代码。

本需求扩展 `skill.yaml` 的 `tools` 段，新增三种原生命令工具类型（`shell`、`script`、`exec`），使技能可以直接在 YAML 中声明外部命令执行，无需编写 Python 代码。三种类型均通过 `asyncio.create_subprocess_shell` / `asyncio.create_subprocess_exec` 执行，复用现有 ShellTool 的子进程管理模式（超时、输出截断、deny pattern 安全策略）。

现有 Python `entry_point` 类型保持完全不变，新类型通过 `tools` 段中的 `type` 字段自动识别；未指定 `type` 时回退到现有 Python entry_point 行为。

技术栈：Python 3.12+、asyncio subprocess、PyYAML、LangChain BaseTool、structlog、pytest + hypothesis。

相关代码：
- `smartclaw/smartclaw/skills/models.py` — ToolDef 数据类（当前字段：name, description, function）
- `smartclaw/smartclaw/skills/loader.py` — SkillsLoader（YAML 解析与技能加载）
- `smartclaw/smartclaw/skills/registry.py` — SkillsRegistry（技能注册与 ToolRegistry 集成）
- `smartclaw/smartclaw/tools/shell.py` — ShellTool（子进程执行参考实现）
- `smartclaw/smartclaw/tools/base.py` — SmartClawTool 基类

## Glossary

- **SmartClaw**: 基于 LangChain + LangGraph 的 Python AI Agent 项目
- **Skill_Definition**: YAML 格式的技能定义文件（`skill.yaml`），描述技能的名称、描述、参数和工具列表
- **ToolDef**: 技能内嵌工具定义数据类，描述单个工具的名称、描述和执行方式
- **NativeCommandTool**: 原生命令工具的统称，包括 shell、script、exec 三种类型，通过 asyncio subprocess 执行外部命令
- **ShellTypeTool**: `type: shell` 类型工具，执行内联 shell 命令字符串（通过 `create_subprocess_shell`）
- **ScriptTypeTool**: `type: script` 类型工具，执行可执行脚本文件（shell 脚本、Python 脚本等）
- **ExecTypeTool**: `type: exec` 类型工具，执行编译后的外部程序（Go 二进制、系统命令等，通过 `create_subprocess_exec`）
- **ParameterDef**: 工具参数定义，描述参数的名称、类型、描述和默认值，用于 LLM 工具调用时的参数传递
- **Placeholder_Substitution**: 占位符替换机制，将 `{param_name}` 格式的占位符替换为 LLM 工具调用传入的实际参数值
- **Deny_Pattern**: 安全拒绝模式，正则表达式列表，匹配的命令将被阻止执行
- **SkillsLoader**: 技能加载器，负责从文件系统发现和加载 YAML 格式的技能定义文件
- **SkillsRegistry**: 技能注册表，管理已加载技能的注册、查询和 ToolRegistry 集成
- **ToolRegistry**: 工具注册中心，管理 LangChain BaseTool 实例
- **SmartClawTool**: 所有非浏览器工具的抽象基类，继承 LangChain `BaseTool`，提供 `_safe_run` 异步错误包装
- **ShellTool**: 现有的 Shell 命令执行工具（`smartclaw/tools/shell.py`），作为子进程执行的参考实现

## Requirements

### Requirement 1: ToolDef 数据模型扩展 — 支持原生命令工具类型

**User Story:** As a skill developer, I want the ToolDef data model to support native command tool types (shell, script, exec) alongside the existing Python function type, so that I can define external command tools directly in skill.yaml without writing Python wrapper code.

#### Acceptance Criteria

1. THE ToolDef SHALL include an optional `type` field (string) that accepts values: `"shell"`, `"script"`, `"exec"`, or `None` (default)
2. WHEN `type` is `None` or not specified, THE ToolDef SHALL represent a traditional Python entry_point tool, and the `function` field SHALL be required
3. WHEN `type` is `"shell"`, `"script"`, or `"exec"`, THE ToolDef SHALL require a `command` field (string) specifying the command to execute
4. THE ToolDef SHALL include an optional `args` field (list of strings) for specifying command-line arguments, applicable to `exec` type tools
5. THE ToolDef SHALL include an optional `working_dir` field (string) specifying the working directory for command execution, supporting `{workspace}` placeholder substitution
6. THE ToolDef SHALL include an optional `timeout` field (integer, default 60) specifying the maximum execution time in seconds
7. THE ToolDef SHALL include an optional `max_output_chars` field (integer, default 10000) specifying the maximum output character count before truncation
8. THE ToolDef SHALL include an optional `deny_patterns` field (list of strings) specifying regex patterns for commands that should be blocked
9. THE ToolDef SHALL include an optional `parameters` field (dict mapping parameter name to ParameterDef) defining the tool's input parameters for LLM tool calls
10. THE ParameterDef SHALL include fields: `type` (string, e.g. `"string"`, `"integer"`, `"boolean"`), `description` (string), and optional `default` (any value)
11. THE ToolDef `validate` method SHALL return an error when `type` is `"shell"`, `"script"`, or `"exec"` and the `command` field is empty or missing
12. THE ToolDef `validate` method SHALL return an error when `type` is `None` and the `function` field is empty or missing
13. THE ToolDef `validate` method SHALL return an error when `type` is set to an unrecognized value (not `"shell"`, `"script"`, `"exec"`, or `None`)

### Requirement 2: skill.yaml 解析扩展 — 原生命令工具解析

**User Story:** As a skill developer, I want the SkillsLoader YAML parser to correctly parse native command tool definitions from skill.yaml, so that all tool types are properly loaded and available for registration.

#### Acceptance Criteria

1. WHEN a tool entry in skill.yaml contains a `type` field with value `"shell"`, `"script"`, or `"exec"`, THE SkillsLoader `parse_skill_yaml` SHALL parse the entry into a ToolDef with the corresponding type and command fields populated
2. WHEN a tool entry in skill.yaml does not contain a `type` field, THE SkillsLoader `parse_skill_yaml` SHALL parse the entry as a traditional Python function tool (backward compatible)
3. THE SkillsLoader `parse_skill_yaml` SHALL parse the `args` field as a list of strings when present in a tool entry
4. THE SkillsLoader `parse_skill_yaml` SHALL parse the `parameters` field as a dict of ParameterDef objects when present in a tool entry
5. THE SkillsLoader `parse_skill_yaml` SHALL parse `working_dir`, `timeout`, `max_output_chars`, and `deny_patterns` fields when present in a tool entry
6. THE SkillsLoader `serialize_skill_yaml` SHALL correctly serialize ToolDef objects with native command type fields back to YAML format
7. FOR ALL valid SkillDefinition objects containing native command tools, parsing the serialized YAML output and comparing with the original object SHALL produce an equivalent SkillDefinition (round-trip property)

### Requirement 3: 占位符替换机制 — 参数注入

**User Story:** As a skill developer, I want to use `{param_name}` placeholders in command strings and args, so that LLM tool call parameters are automatically substituted into the command before execution.

#### Acceptance Criteria

1. THE Placeholder_Substitution module SHALL replace all `{param_name}` occurrences in the command string with the corresponding parameter values from the LLM tool call
2. THE Placeholder_Substitution module SHALL replace all `{param_name}` occurrences in each element of the `args` list with the corresponding parameter values
3. THE Placeholder_Substitution module SHALL replace `{workspace}` in the `working_dir` field with the actual workspace directory path
4. WHEN a parameter referenced by a placeholder is not provided in the tool call and has a default value in ParameterDef, THE Placeholder_Substitution module SHALL use the default value
5. WHEN a parameter referenced by a placeholder is not provided and has no default value, THE Placeholder_Substitution module SHALL return an error indicating the missing required parameter
6. THE Placeholder_Substitution module SHALL convert non-string parameter values to their string representation before substitution
7. FOR ALL command strings with N placeholders and N corresponding parameter values, substituting the parameters and extracting them back (where possible) SHALL preserve the original parameter values (round-trip property for simple cases)

### Requirement 4: ShellTypeTool — 内联 Shell 命令执行

**User Story:** As a skill developer, I want to define inline shell commands in skill.yaml that execute via asyncio subprocess, so that simple shell operations can be exposed as LLM tools without Python code.

#### Acceptance Criteria

1. WHEN a `type: shell` tool is invoked, THE NativeCommandTool SHALL execute the command string via `asyncio.create_subprocess_shell` after placeholder substitution
2. THE ShellTypeTool SHALL capture both stdout and stderr from the subprocess
3. WHEN the subprocess completes successfully, THE ShellTypeTool SHALL return the combined stdout and stderr output as a string, with stderr prefixed by `"STDERR:\n"` when non-empty
4. WHEN the subprocess exits with a non-zero exit code, THE ShellTypeTool SHALL include the exit code in the returned output string
5. WHEN the subprocess exceeds the configured timeout, THE ShellTypeTool SHALL terminate the process and return an error string containing the timeout duration
6. WHEN the output exceeds the configured `max_output_chars`, THE ShellTypeTool SHALL truncate the output and append a truncation indicator with the number of omitted characters
7. WHEN the command matches any configured `deny_patterns` regex, THE ShellTypeTool SHALL return an error indicating the command was blocked by security policy
8. WHEN `working_dir` is configured, THE ShellTypeTool SHALL execute the command in the specified directory
9. WHEN `working_dir` is configured but the directory does not exist, THE ShellTypeTool SHALL return an error indicating the working directory was not found

### Requirement 5: ScriptTypeTool — 可执行脚本执行

**User Story:** As a skill developer, I want to define executable script paths in skill.yaml that run via asyncio subprocess, so that shell scripts, Python scripts, and other executable files can be exposed as LLM tools.

#### Acceptance Criteria

1. WHEN a `type: script` tool is invoked, THE NativeCommandTool SHALL execute the script file specified in the `command` field via `asyncio.create_subprocess_shell`, passing parameters as command-line arguments after placeholder substitution
2. THE ScriptTypeTool SHALL capture both stdout and stderr from the subprocess
3. WHEN the subprocess completes successfully, THE ScriptTypeTool SHALL return the combined stdout and stderr output as a string, with stderr prefixed by `"STDERR:\n"` when non-empty
4. WHEN the subprocess exits with a non-zero exit code, THE ScriptTypeTool SHALL include the exit code in the returned output string
5. WHEN the subprocess exceeds the configured timeout, THE ScriptTypeTool SHALL terminate the process and return an error string containing the timeout duration
6. WHEN the output exceeds the configured `max_output_chars`, THE ScriptTypeTool SHALL truncate the output and append a truncation indicator
7. WHEN the command matches any configured `deny_patterns` regex, THE ScriptTypeTool SHALL return an error indicating the command was blocked by security policy
8. WHEN `working_dir` is configured, THE ScriptTypeTool SHALL execute the script in the specified directory
9. WHEN the script file specified in `command` does not exist, THE ScriptTypeTool SHALL return an error indicating the script was not found

### Requirement 6: ExecTypeTool — 编译程序执行

**User Story:** As a skill developer, I want to define compiled program paths in skill.yaml that run via asyncio subprocess exec, so that Go binaries, Rust binaries, and other compiled programs can be exposed as LLM tools.

#### Acceptance Criteria

1. WHEN a `type: exec` tool is invoked, THE NativeCommandTool SHALL execute the program specified in the `command` field via `asyncio.create_subprocess_exec` with the `args` list (after placeholder substitution) as command-line arguments
2. THE ExecTypeTool SHALL capture both stdout and stderr from the subprocess
3. WHEN the subprocess completes successfully, THE ExecTypeTool SHALL return the combined stdout and stderr output as a string, with stderr prefixed by `"STDERR:\n"` when non-empty
4. WHEN the subprocess exits with a non-zero exit code, THE ExecTypeTool SHALL include the exit code in the returned output string
5. WHEN the subprocess exceeds the configured timeout, THE ExecTypeTool SHALL terminate the process and return an error string containing the timeout duration
6. WHEN the output exceeds the configured `max_output_chars`, THE ExecTypeTool SHALL truncate the output and append a truncation indicator
7. WHEN the command matches any configured `deny_patterns` regex, THE ExecTypeTool SHALL return an error indicating the command was blocked by security policy
8. WHEN `working_dir` is configured, THE ExecTypeTool SHALL execute the program in the specified directory
9. WHEN the program specified in `command` cannot be found in PATH, THE ExecTypeTool SHALL return an error indicating the program was not found

### Requirement 7: NativeCommandTool 工厂 — 从 ToolDef 创建 BaseTool

**User Story:** As a system integrator, I want a factory function that creates LangChain BaseTool instances from native command ToolDef definitions, so that the SkillsRegistry can automatically register native command tools alongside Python entry_point tools.

#### Acceptance Criteria

1. THE NativeCommandTool factory SHALL accept a ToolDef with `type` set to `"shell"`, `"script"`, or `"exec"` and return a LangChain BaseTool instance
2. THE created BaseTool SHALL have its `name` set to the ToolDef `name` field
3. THE created BaseTool SHALL have its `description` set to the ToolDef `description` field
4. THE created BaseTool SHALL dynamically generate a Pydantic `args_schema` from the ToolDef `parameters` field, mapping each parameter to the corresponding Pydantic field type
5. THE created BaseTool SHALL inherit from SmartClawTool and use the `_safe_run` wrapper for error handling
6. WHEN the ToolDef `type` is not `"shell"`, `"script"`, or `"exec"`, THE factory SHALL raise a ValueError indicating the unsupported tool type

### Requirement 8: SkillsRegistry 集成 — 原生命令工具注册

**User Story:** As a system integrator, I want the SkillsRegistry to automatically detect and register native command tools from skill.yaml, so that both Python entry_point tools and native command tools are available to the Agent Graph.

#### Acceptance Criteria

1. WHEN a Skill_Definition contains tools with `type` set to `"shell"`, `"script"`, or `"exec"`, THE SkillsRegistry SHALL use the NativeCommandTool factory to create BaseTool instances and register them in the ToolRegistry
2. WHEN a Skill_Definition contains tools without a `type` field, THE SkillsRegistry SHALL continue using the existing Python entry_point loading mechanism (backward compatible)
3. WHEN a Skill_Definition contains a mix of Python entry_point tools and native command tools, THE SkillsRegistry SHALL register both types correctly
4. WHEN a native command tool registration fails (invalid ToolDef, factory error), THE SkillsRegistry SHALL log the error via structlog and continue registering remaining tools
5. THE SkillsRegistry SHALL support skills that define only native command tools without an `entry_point` field in the Skill_Definition

### Requirement 9: SkillDefinition 验证扩展 — 支持无 entry_point 技能

**User Story:** As a skill developer, I want to create skills that contain only native command tools without requiring a Python entry_point, so that I can build pure YAML skills without any Python code.

#### Acceptance Criteria

1. WHEN a Skill_Definition has no `entry_point` field but contains at least one tool with a valid native command `type`, THE SkillDefinition `validate` method SHALL accept the definition as valid
2. WHEN a Skill_Definition has no `entry_point` field and no native command tools, THE SkillDefinition `validate` method SHALL return an error indicating that either `entry_point` or native command tools are required
3. WHEN a Skill_Definition has both an `entry_point` field and native command tools, THE SkillDefinition `validate` method SHALL accept the definition as valid (hybrid skill)

### Requirement 10: 向后兼容性

**User Story:** As a developer, I want all existing skills using Python entry_point to continue working without any modification, so that the native command tool extension does not break existing functionality.

#### Acceptance Criteria

1. THE existing Python `entry_point` skill loading mechanism SHALL remain unchanged and fully functional
2. THE existing ToolDef data model SHALL maintain backward compatibility — existing skill.yaml files without `type` fields SHALL parse and load identically to the current behavior
3. THE existing SkillsLoader `parse_skill_yaml` and `serialize_skill_yaml` methods SHALL produce identical results for skill.yaml files that do not use native command tool types
4. THE existing SkillsRegistry `load_and_register_all` method SHALL handle both Python entry_point skills and native command skills in the same discovery/registration pass

### Requirement 11: SKILL.md 提示词型技能 — Markdown 格式支持

**User Story:** As a skill developer, I want to define skills using Markdown files (SKILL.md) with YAML frontmatter, so that I can create prompt-based skills that guide LLM behavior through natural language instructions, matching the format used by PicoClaw and OpenClaw.

#### Acceptance Criteria

1. THE SkillsLoader SHALL discover skills by scanning for both `{skill_name}/skill.yaml` (工具型) AND `{skill_name}/SKILL.md` (提示词型) files in skill directories
2. WHEN a skill directory contains a `SKILL.md` file, THE SkillsLoader SHALL parse the YAML frontmatter (between `---` delimiters) to extract `name` and `description` metadata
3. WHEN a `SKILL.md` file has no YAML frontmatter, THE SkillsLoader SHALL use the directory name as the skill name and the first paragraph of the Markdown body as the description
4. THE SkillsLoader SHALL strip the YAML frontmatter from the Markdown content and return the body text as the skill's prompt content
5. WHEN a skill directory contains both `skill.yaml` and `SKILL.md`, THE SkillsLoader SHALL load both — `skill.yaml` provides tools and `SKILL.md` provides prompt content (hybrid skill)
6. WHEN a skill directory contains only `SKILL.md` (no `skill.yaml`), THE SkillsLoader SHALL treat it as a pure prompt skill with no tools, and the Markdown body SHALL be injected into the Agent's system prompt context
7. THE SkillsLoader `load_skill` method SHALL return the SKILL.md body content when loading a Markdown-based skill
8. THE SkillsLoader `build_skills_summary` method SHALL include Markdown-based skills in the summary, using the frontmatter `name` and `description`
9. THE SkillsLoader `load_skills_for_context` method SHALL load SKILL.md content for specified skill names and concatenate them for injection into the LLM context
10. THE SKILL.md format SHALL support the following YAML frontmatter fields: `name` (string, optional — defaults to directory name), `description` (string, optional — defaults to first paragraph)
11. WHEN a SKILL.md file contains invalid YAML frontmatter, THE SkillsLoader SHALL log a warning and fall back to using the directory name and first paragraph as metadata

### Requirement 12: 技能目录结构统一 — 三种技能格式共存

**User Story:** As a skill developer, I want a unified skill directory structure that supports all three skill formats (YAML tools, native commands, Markdown prompts) in the same directory, so that I can create rich skills combining tools and prompts.

#### Acceptance Criteria

1. THE SkillsLoader SHALL support the following skill directory structures:
   - Pure YAML tool skill: `{skill_name}/skill.yaml` (with entry_point or native command tools)
   - Pure Markdown prompt skill: `{skill_name}/SKILL.md`
   - Hybrid skill: `{skill_name}/skill.yaml` + `{skill_name}/SKILL.md` (tools + prompt)
2. WHEN discovering skills, THE SkillsLoader SHALL consider a directory as a valid skill if it contains at least one of `skill.yaml` or `SKILL.md`
3. THE priority order for skill discovery SHALL remain: workspace > global > builtin, with same-name deduplication at the skill level (not file level)
