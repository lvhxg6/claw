# Requirements Document

## Introduction

SmartClaw Tool System 是 SmartClaw P0 阶段的 Spec 4，覆盖非浏览器工具基础设施。本规格定义工具注册框架（基类、注册中心、发现）、文件系统工具（读/写/列目录）、Shell 工具（命令执行）、Web 搜索工具（Tavily 集成）以及基础安全（路径白名单/黑名单）。所有工具均实现为 LangChain `BaseTool`，可直接注入 Agent Graph ReAct 循环。

参考架构：PicoClaw `pkg/tools/`（Go 实现），已有浏览器工具 `smartclaw/tools/browser_tools.py`（Spec 3）。

## Glossary

- **Tool_Registry**: 工具注册中心，负责注册、发现、列举所有可用工具实例，并将它们合并为统一的 `list[BaseTool]` 供 Agent Graph 使用
- **Tool_Base**: 所有非浏览器工具的抽象基类，继承 LangChain `BaseTool`，提供统一的错误处理包装和元数据约定
- **Path_Policy**: 路径安全策略引擎，基于 pathlib 实现白名单/黑名单规则，决定文件系统操作是否被允许
- **Filesystem_Tool**: 文件系统工具集合，包含 read_file、write_file、list_directory 三个 LangChain Tool
- **Shell_Tool**: 命令执行工具，通过 asyncio.subprocess 运行 shell 命令，支持超时控制和输出捕获
- **Web_Search_Tool**: Web 搜索工具，通过 tavily-python 执行互联网搜索并返回结构化结果
- **Agent_Graph**: Spec 2 中定义的 LangGraph ReAct StateGraph，消费 `list[BaseTool]` 驱动推理-行动循环
- **Safe_Tool_Call**: 统一的异常捕获包装模式，将所有异常转换为人类可读的错误字符串返回给 LLM，而非抛出异常（与 browser_tools.py 中 `_safe_tool_call` 模式一致）

## Requirements

### Requirement 1: Tool Base Class

**User Story:** As a developer, I want a common base class for all non-browser tools, so that every tool follows a consistent interface and error handling pattern.

#### Acceptance Criteria

1. THE Tool_Base SHALL inherit from LangChain `BaseTool` and define `name`, `description`, and `args_schema` attributes
2. THE Tool_Base SHALL provide a `_safe_run` async wrapper method that catches all exceptions and returns human-readable error strings
3. WHEN a tool execution raises any exception, THE Tool_Base `_safe_run` wrapper SHALL catch the exception and return a string in the format `"Error: {error_message}"`
4. THE Tool_Base SHALL define a synchronous `_run` method that raises `NotImplementedError` with the message `"Use async"`
5. THE Tool_Base SHALL log errors via structlog with component name `"tools.{tool_name}"` before returning the error string

### Requirement 2: Tool Registry

**User Story:** As a developer, I want a central registry that collects all tool instances, so that the Agent Graph receives a single unified tool list.

#### Acceptance Criteria

1. THE Tool_Registry SHALL provide a `register` method that accepts a single `BaseTool` instance and stores it by name
2. THE Tool_Registry SHALL provide a `register_many` method that accepts a list of `BaseTool` instances
3. THE Tool_Registry SHALL provide a `get` method that returns a tool by name, or `None` if the tool does not exist
4. THE Tool_Registry SHALL provide a `list_tools` method that returns all registered tool names as a sorted list of strings
5. THE Tool_Registry SHALL provide a `get_all` method that returns all registered tools as a `list[BaseTool]`
6. WHEN a tool with a duplicate name is registered, THE Tool_Registry SHALL replace the existing tool and log a warning
7. THE Tool_Registry SHALL provide a `merge` method that accepts another Tool_Registry instance and adds all its tools to the current registry
8. THE Tool_Registry SHALL provide a `count` property that returns the number of registered tools as an integer

### Requirement 3: Filesystem Tools

**User Story:** As an agent, I want to read, write, and list files on the local filesystem, so that I can inspect and modify project files during task execution.

#### Acceptance Criteria

1. WHEN a valid file path is provided, THE Filesystem_Tool `read_file` SHALL return the file content as a string
2. WHEN a file path does not exist, THE Filesystem_Tool `read_file` SHALL return an error string containing the path
3. WHEN a valid file path and content are provided, THE Filesystem_Tool `write_file` SHALL write the content to the file and return a success confirmation string
4. WHEN the parent directory of the target file does not exist, THE Filesystem_Tool `write_file` SHALL create the parent directories before writing
5. WHEN a valid directory path is provided, THE Filesystem_Tool `list_directory` SHALL return a formatted listing of directory entries with file type indicators
6. WHEN a directory path does not exist, THE Filesystem_Tool `list_directory` SHALL return an error string containing the path
7. WHEN a file path violates the Path_Policy, THE Filesystem_Tool SHALL return an error string `"Error: Access denied — path '{path}' is not allowed by security policy"` without performing the operation
8. THE Filesystem_Tool `read_file` SHALL accept an optional `max_bytes` parameter that limits the number of bytes read, defaulting to 1,048,576 (1 MB)
9. WHEN the file size exceeds `max_bytes`, THE Filesystem_Tool `read_file` SHALL return the truncated content with a suffix indicating truncation

### Requirement 4: Shell Tool

**User Story:** As an agent, I want to execute shell commands, so that I can run build scripts, tests, and other CLI operations during task execution.

#### Acceptance Criteria

1. WHEN a command string is provided, THE Shell_Tool SHALL execute the command via `asyncio.create_subprocess_shell` and return the combined stdout and stderr output
2. THE Shell_Tool SHALL accept a configurable `timeout_seconds` parameter, defaulting to 60 seconds
3. WHEN a command exceeds the timeout, THE Shell_Tool SHALL terminate the process and return an error string containing the timeout duration and any partial output captured before timeout
4. THE Shell_Tool SHALL accept an optional `working_dir` parameter that sets the working directory for command execution
5. WHEN the `working_dir` does not exist, THE Shell_Tool SHALL return an error string indicating the directory was not found
6. THE Shell_Tool SHALL capture stdout and stderr separately and combine them in the result, with stderr prefixed by `"STDERR:\n"`
7. WHEN the command exits with a non-zero exit code, THE Shell_Tool SHALL include the exit code in the returned string
8. THE Shell_Tool SHALL truncate output exceeding 10,000 characters and append a truncation indicator with the number of omitted characters
9. THE Shell_Tool SHALL apply a configurable deny-pattern list to block dangerous commands (e.g., `rm -rf`, `sudo`, `shutdown`) and return an error string when a command matches a deny pattern

### Requirement 5: Web Search Tool

**User Story:** As an agent, I want to search the web for information, so that I can gather up-to-date knowledge to complete research tasks.

#### Acceptance Criteria

1. WHEN a search query is provided, THE Web_Search_Tool SHALL call the Tavily search API and return the results as a formatted string
2. THE Web_Search_Tool SHALL accept a configurable `max_results` parameter, defaulting to 5
3. THE Web_Search_Tool SHALL read the Tavily API key from environment variable `TAVILY_API_KEY`
4. IF the `TAVILY_API_KEY` environment variable is not set, THEN THE Web_Search_Tool SHALL return an error string `"Error: TAVILY_API_KEY environment variable is not set"`
5. WHEN the Tavily API returns an error, THE Web_Search_Tool SHALL return an error string containing the API error message
6. THE Web_Search_Tool SHALL format each search result as a block containing title, URL, and content snippet

### Requirement 6: Path Security Policy

**User Story:** As a system administrator, I want to configure which filesystem paths the agent can access, so that sensitive files and directories are protected from unauthorized access.

#### Acceptance Criteria

1. THE Path_Policy SHALL accept a list of allowed path patterns (whitelist) and a list of denied path patterns (blacklist)
2. WHEN both whitelist and blacklist are configured, THE Path_Policy SHALL evaluate the blacklist first — a path matching any blacklist pattern SHALL be denied regardless of whitelist
3. WHEN a whitelist is configured and non-empty, THE Path_Policy SHALL deny any path that does not match at least one whitelist pattern
4. THE Path_Policy SHALL deny access to common sensitive paths by default: `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/gcloud`, `/etc/shadow`, `/etc/passwd`
5. THE Path_Policy SHALL resolve symlinks before evaluating path rules to prevent symlink-based bypass
6. THE Path_Policy SHALL normalize all paths to absolute form using `pathlib.Path.resolve()` before evaluation
7. THE Path_Policy SHALL provide an `is_allowed` method that accepts a path string and returns a boolean
8. THE Path_Policy SHALL provide a `check` method that accepts a path string and raises a `PathDeniedError` if the path is not allowed
9. THE Path_Policy SHALL support glob patterns (e.g., `/tmp/**`, `*.log`) in both whitelist and blacklist entries

### Requirement 7: Tool-Agent Integration

**User Story:** As a developer, I want all system tools to integrate seamlessly with the existing Agent Graph, so that the agent can use browser tools and system tools together in the same ReAct loop.

#### Acceptance Criteria

1. THE Tool_Registry SHALL produce a `list[BaseTool]` compatible with the `build_graph` function in `smartclaw/agent/graph.py`
2. WHEN browser tools and system tools are both registered, THE Tool_Registry `get_all` method SHALL return a combined list containing both tool categories
3. THE Tool_Registry SHALL provide a `create_system_tools` factory function that instantiates all system tools (filesystem, shell, web search) with a given workspace path and Path_Policy configuration
4. WHEN `create_system_tools` is called, THE factory function SHALL return a Tool_Registry instance containing all system tool instances ready for use
