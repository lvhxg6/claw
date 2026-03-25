# Implementation Plan: SmartClaw Tool System

## Overview

Implement the non-browser tool infrastructure (Spec 4) for SmartClaw. This includes the tool base class (`SmartClawTool`), tool registry (`ToolRegistry`), filesystem tools (read/write/list), shell tool (command execution), web search tool (Tavily), and path security policy engine (`PathPolicy`).

All new code lives under `smartclaw/smartclaw/tools/` and `smartclaw/smartclaw/security/`, with tests under `smartclaw/tests/tools/` and `smartclaw/tests/security/`. The `tavily-python` dependency must be added to `pyproject.toml`.

## Tasks

- [x] 1. Project setup and security module scaffolding
  - [x] 1.1 Add `tavily-python` to `pyproject.toml` dependencies
    - Add `tavily-python>=0.3.0` to `[project.dependencies]`
    - _Requirements: 5.1, 5.3_

  - [x] 1.2 Create `smartclaw/smartclaw/security/__init__.py` and `smartclaw/smartclaw/security/path_policy.py`
    - Create `security/` package with `__init__.py` exporting `PathPolicy` and `PathDeniedError`
    - Implement `PathDeniedError` exception class with `path` attribute and descriptive message
    - _Requirements: 6.8_

  - [x] 1.3 Create `smartclaw/tests/security/__init__.py` test package
    - Create empty `__init__.py` for the security test directory
    - _Requirements: N/A (scaffolding)_

- [x] 2. PathPolicy engine
  - [x] 2.1 Implement `PathPolicy` class in `smartclaw/smartclaw/security/path_policy.py`
    - Implement `__init__(allowed_patterns, denied_patterns)` with `DEFAULT_DENIED_PATHS` always included in blacklist
    - Implement `is_allowed(path)` — resolve path via `pathlib.Path.resolve()`, evaluate blacklist first, then whitelist; support glob patterns via `fnmatch`
    - Implement `check(path)` — call `is_allowed`, raise `PathDeniedError` if denied
    - Resolve symlinks before evaluation to prevent bypass
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [x] 2.2 Write property test for blacklist-first evaluation
    - **Property 17: PathPolicy blacklist-first evaluation**
    - For any path matching both whitelist and blacklist, `is_allowed` returns `False`; for any path not matching any whitelist pattern (when whitelist is non-empty), `is_allowed` returns `False`
    - File: `smartclaw/tests/security/test_path_policy_props.py`
    - **Validates: Requirements 6.2, 6.3**

  - [x] 2.3 Write property test for path normalization
    - **Property 18: PathPolicy path normalization**
    - For any relative path and its absolute equivalent (resolved via `pathlib.Path.resolve()`), PathPolicy produces the same `is_allowed` result for both
    - File: `smartclaw/tests/security/test_path_policy_props.py`
    - **Validates: Requirements 6.5, 6.6**

  - [x] 2.4 Write property test for check/is_allowed consistency
    - **Property 19: PathPolicy check/is_allowed consistency**
    - For any path string, `check(path)` raises `PathDeniedError` if and only if `is_allowed(path)` returns `False`
    - File: `smartclaw/tests/security/test_path_policy_props.py`
    - **Validates: Requirements 6.8**

  - [x] 2.5 Write property test for glob pattern matching
    - **Property 20: PathPolicy glob pattern matching**
    - For any glob pattern in whitelist and any matching path, `is_allowed` returns `True` (assuming no blacklist match); for any glob in blacklist and any matching path, `is_allowed` returns `False`
    - File: `smartclaw/tests/security/test_path_policy_props.py`
    - **Validates: Requirements 6.9**

  - [x] 2.6 Write unit tests for PathPolicy
    - Test default denied paths (`~/.ssh`, `~/.aws`, etc.) are blocked (Req 6.4)
    - Test symlink bypass prevention (Req 6.5)
    - Test empty whitelist allows all non-blacklisted paths
    - File: `smartclaw/tests/security/test_path_policy.py`
    - _Requirements: 6.4, 6.5_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. SmartClawTool base class
  - [x] 4.1 Implement `SmartClawTool` abstract base class in `smartclaw/smartclaw/tools/base.py`
    - Inherit from `langchain_core.tools.BaseTool`
    - Define `name`, `description`, `args_schema` attributes
    - Implement `_run` raising `NotImplementedError("Use async")`
    - Implement `_safe_run(coro)` async wrapper: catch all exceptions, log via structlog with component `"tools.{tool_name}"`, return `"Error: {message}"`
    - Declare abstract `_arun` method
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 4.2 Write property test for _safe_run error format
    - **Property 1: _safe_run catches all exceptions and returns formatted error string**
    - For any exception type and error message, `_safe_run` wrapping a raising coroutine returns `"Error: {error_message}"`
    - File: `smartclaw/tests/tools/test_base_props.py`
    - **Validates: Requirements 1.2, 1.3**

  - [x] 4.3 Write unit tests for SmartClawTool
    - Test `_run` raises `NotImplementedError` (Req 1.4)
    - Test structlog component name format `"tools.{tool_name}"` (Req 1.5)
    - File: `smartclaw/tests/tools/test_base.py`
    - _Requirements: 1.4, 1.5_

- [x] 5. ToolRegistry
  - [x] 5.1 Implement `ToolRegistry` class in `smartclaw/smartclaw/tools/registry.py`
    - Implement `register(tool)`, `register_many(tools)`, `get(name)`, `list_tools()` (sorted), `get_all()`, `merge(other)`, `count` property
    - Log warning on duplicate name registration before replacing
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 5.2 Write property test for register/get round-trip
    - **Property 2: Registry register/get round-trip**
    - For any list of tools with unique names, after registering, `get(name)` returns the corresponding tool instance
    - File: `smartclaw/tests/tools/test_registry_props.py`
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [x] 5.3 Write property test for list_tools sorted order
    - **Property 3: Registry list_tools returns sorted names**
    - For any set of registered tools, `list_tools()` returns sorted ascending lexicographic order with exactly all registered names
    - File: `smartclaw/tests/tools/test_registry_props.py`
    - **Validates: Requirements 2.4**

  - [x] 5.4 Write property test for size invariant
    - **Property 4: Registry size invariant**
    - For any set of tools with unique names, `count` equals `len(get_all())` and both equal the number of unique names registered
    - File: `smartclaw/tests/tools/test_registry_props.py`
    - **Validates: Requirements 2.5, 2.8**

  - [x] 5.5 Write property test for duplicate replacement
    - **Property 5: Registry duplicate replacement**
    - For two tools sharing the same name, registering first then second results in `get(name)` returning the second; `count` remains 1
    - File: `smartclaw/tests/tools/test_registry_props.py`
    - **Validates: Requirements 2.6**

  - [x] 5.6 Write property test for merge set union
    - **Property 6: Registry merge is set union**
    - For two registries with disjoint names, after merge, first registry contains all tools from both; `count` equals sum of original counts
    - File: `smartclaw/tests/tools/test_registry_props.py`
    - **Validates: Requirements 2.7**

  - [x] 5.7 Write unit tests for ToolRegistry
    - Test `get` returns `None` for missing name (Req 2.3)
    - Test duplicate registration logs warning (Req 2.6)
    - File: `smartclaw/tests/tools/test_registry.py`
    - _Requirements: 2.3, 2.6_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Filesystem tools
  - [x] 7.1 Implement Pydantic input schemas in `smartclaw/smartclaw/tools/filesystem.py`
    - Implement `ReadFileInput`, `WriteFileInput`, `ListDirectoryInput` with fields as specified in design
    - _Requirements: 3.1, 3.3, 3.5_

  - [x] 7.2 Implement `ReadFileTool`, `WriteFileTool`, `ListDirectoryTool` in `smartclaw/smartclaw/tools/filesystem.py`
    - All three extend `SmartClawTool`
    - `ReadFileTool`: read file content, respect `max_bytes` truncation (default 1MB), add truncation suffix when exceeded
    - `WriteFileTool`: write content, create parent directories if missing, return success confirmation
    - `ListDirectoryTool`: list directory entries with file type indicators
    - All tools call `PathPolicy.check()` before I/O; catch `PathDeniedError` and return formatted error string
    - Use `_safe_run` wrapper for all operations
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 7.3 Write property test for write/read round-trip
    - **Property 7: Filesystem write/read round-trip**
    - For any valid path and string content, writing then reading returns the original content
    - Use `tmp_path` fixture and hypothesis text strategies
    - File: `smartclaw/tests/tools/test_filesystem_props.py`
    - **Validates: Requirements 3.1, 3.3**

  - [x] 7.4 Write property test for error contains path
    - **Property 8: Filesystem error contains path**
    - For any non-existent file path, `read_file` returns a string containing the path; same for non-existent directory with `list_directory`
    - File: `smartclaw/tests/tools/test_filesystem_props.py`
    - **Validates: Requirements 3.2, 3.6**

  - [x] 7.5 Write property test for policy enforcement
    - **Property 9: Filesystem policy enforcement**
    - For any path denied by PathPolicy, all filesystem tools return the error string `"Error: Access denied — path '{path}' is not allowed by security policy"` without performing I/O
    - File: `smartclaw/tests/tools/test_filesystem_props.py`
    - **Validates: Requirements 3.7**

  - [x] 7.6 Write property test for read truncation
    - **Property 10: Filesystem read truncation**
    - For any file exceeding `max_bytes`, `read_file` returns content of at most `max_bytes` length with a truncation suffix
    - File: `smartclaw/tests/tools/test_filesystem_props.py`
    - **Validates: Requirements 3.8, 3.9**

  - [x] 7.7 Write unit tests for filesystem tools
    - Test parent directory creation (Req 3.4)
    - Test `list_directory` format with file type indicators (Req 3.5)
    - Test `read_file` with non-existent file returns error with path (Req 3.2)
    - File: `smartclaw/tests/tools/test_filesystem.py`
    - _Requirements: 3.2, 3.4, 3.5_

- [x] 8. Shell tool
  - [x] 8.1 Implement `ShellInput` schema and `ShellTool` in `smartclaw/smartclaw/tools/shell.py`
    - Extend `SmartClawTool`
    - Execute commands via `asyncio.create_subprocess_shell`
    - Support `timeout_seconds` (default 60), `working_dir` parameters
    - Capture stdout/stderr separately; combine with stderr prefixed by `"STDERR:\n"`
    - Include exit code in output for non-zero exits
    - Truncate output exceeding 10,000 characters with truncation indicator
    - Apply deny-pattern list (`DEFAULT_DENY_PATTERNS`) to block dangerous commands
    - Kill process on timeout, return error with partial output
    - Return error when `working_dir` does not exist
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 8.2 Write property test for deny pattern blocking
    - **Property 11: Shell deny pattern blocking**
    - For any command matching at least one deny pattern, ShellTool returns error without executing; for any command not matching, ShellTool proceeds
    - File: `smartclaw/tests/tools/test_shell_props.py`
    - **Validates: Requirements 4.9**

  - [x] 8.3 Write property test for stderr prefix format
    - **Property 12: Shell output format with stderr prefix**
    - For any command producing both stdout and stderr, the returned string contains stdout content and stderr prefixed by `"STDERR:\n"`
    - File: `smartclaw/tests/tools/test_shell_props.py`
    - **Validates: Requirements 4.6**

  - [x] 8.4 Write property test for exit code in output
    - **Property 13: Shell exit code in output**
    - For any command exiting with non-zero code N, the returned string contains the string representation of N
    - File: `smartclaw/tests/tools/test_shell_props.py`
    - **Validates: Requirements 4.7**

  - [x] 8.5 Write property test for output truncation
    - **Property 14: Shell output truncation**
    - For any command whose combined output exceeds 10,000 characters, the returned string is truncated to at most 10,000 chars plus a truncation indicator with omitted character count
    - File: `smartclaw/tests/tools/test_shell_props.py`
    - **Validates: Requirements 4.8**

  - [x] 8.6 Write unit tests for ShellTool
    - Test default timeout 60s (Req 4.2)
    - Test timeout kills process and returns partial output (Req 4.3)
    - Test `working_dir` not found error (Req 4.5)
    - File: `smartclaw/tests/tools/test_shell.py`
    - _Requirements: 4.2, 4.3, 4.5_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Web search tool
  - [x] 10.1 Implement `WebSearchInput` schema and `WebSearchTool` in `smartclaw/smartclaw/tools/web_search.py`
    - Extend `SmartClawTool`
    - Read `TAVILY_API_KEY` from environment; return error if not set
    - Call Tavily search API with `query` and `max_results` (default 5)
    - Format each result as block with title, URL, and content snippet
    - Catch API errors and return formatted error string
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 10.2 Write property test for search result formatting
    - **Property 15: Web search result formatting**
    - For any list of search results with title, URL, and content snippet, the formatted output contains all three fields for every result
    - Use hypothesis to generate lists of result dicts; mock Tavily client
    - File: `smartclaw/tests/tools/test_web_search_props.py`
    - **Validates: Requirements 5.6**

  - [x] 10.3 Write property test for API error passthrough
    - **Property 16: Web search API error passthrough**
    - For any API error message from Tavily client, WebSearchTool returns a string containing that error message
    - File: `smartclaw/tests/tools/test_web_search_props.py`
    - **Validates: Requirements 5.5**

  - [x] 10.4 Write unit tests for WebSearchTool
    - Test default `max_results=5` (Req 5.2)
    - Test API key read from env `TAVILY_API_KEY` (Req 5.3)
    - Test missing API key returns specific error string (Req 5.4)
    - File: `smartclaw/tests/tools/test_web_search.py`
    - _Requirements: 5.2, 5.3, 5.4_

- [x] 11. Factory function and agent integration
  - [x] 11.1 Implement `create_system_tools` factory function in `smartclaw/smartclaw/tools/registry.py`
    - Accept `workspace: str` and optional `PathPolicy`
    - Instantiate all system tools (filesystem, shell, web search) with the given workspace and policy
    - Return a populated `ToolRegistry` instance
    - _Requirements: 7.3, 7.4_

  - [x] 11.2 Wire system tools into Agent Graph
    - Update `smartclaw/smartclaw/agent/graph.py` to support merging system tools with browser tools
    - Ensure `build_graph` receives combined `list[BaseTool]` from both browser and system tool registries
    - _Requirements: 7.1, 7.2_

  - [x] 11.3 Write unit tests for integration
    - Test `create_system_tools` returns a `ToolRegistry` with all expected system tools (filesystem × 3, shell × 1, web search × 1)
    - Test combined browser + system tools produce a valid `list[BaseTool]` for `build_graph`
    - File: `smartclaw/tests/tools/test_integration.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- Each property test must run at least 100 iterations (`@settings(max_examples=100)`)
- Each property test must include the annotation comment: `# Feature: smartclaw-tool-system, Property {N}: {title}`
- Filesystem and shell property tests should use `tmp_path` fixture and `AsyncMock` where appropriate to avoid real I/O side effects
- Web search property tests must mock the Tavily client
- All requirements (1.1–7.4) are covered by implementation and test tasks
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
