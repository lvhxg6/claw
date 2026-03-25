# Implementation Plan: SmartClaw Tools Supplement

## Overview

Implement 3 new tools (EditFileTool, AppendFileTool, WebFetchTool) following SmartClaw's existing tool architecture. Each tool builds incrementally on the previous, with property-based tests validating correctness properties from the design. Final step wires everything into the ToolRegistry.

## Tasks

- [x] 1. Implement EditFileTool and AppendFileTool
  - [x] 1.1 Create `smartclaw/smartclaw/tools/edit.py` with input schemas and core pure function
    - Define `EditFileInput` and `AppendFileInput` Pydantic models
    - Implement `replace_single_occurrence(content, old_text, new_text)` pure function
    - Raises `ValueError` when old_text not found or appears more than once
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [x] 1.2 Implement `EditFileTool` class
    - Inherit from `SmartClawTool`, set name/description/args_schema
    - `_arun` calls `PathPolicy.check(path)`, reads file, calls `replace_single_occurrence`, writes back
    - Handle `PathDeniedError`, `FileNotFoundError`, and `ValueError` with descriptive error strings
    - Wrap async logic in `_safe_run`
    - _Requirements: 1.1, 1.4, 1.5, 1.7_

  - [x] 1.3 Implement `AppendFileTool` class
    - Inherit from `SmartClawTool`, set name/description/args_schema
    - `_arun` calls `PathPolicy.check(path)`, creates parent dirs, appends content
    - Creates file if it does not exist
    - Wrap async logic in `_safe_run`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 1.4 Write property test: edit single-replacement round-trip (`test_edit_props.py`)
    - **Property 1: Edit file single-replacement round-trip**
    - **Validates: Requirements 1.1**

  - [x] 1.5 Write property test: edit rejects non-unique matches (`test_edit_props.py`)
    - **Property 2: Edit file rejects non-unique matches**
    - **Validates: Requirements 1.2, 1.3**

  - [x] 1.6 Write property test: PathPolicy enforcement for edit and append (`test_edit_props.py`)
    - **Property 3: PathPolicy enforcement for edit and append tools**
    - **Validates: Requirements 1.4, 2.3**

  - [x] 1.7 Write property test: append preserves existing content (`test_edit_props.py`)
    - **Property 4: Append preserves existing content**
    - **Validates: Requirements 2.1, 2.2**

  - [x] 1.8 Write property test: _safe_run catches all exceptions (`test_edit_props.py`)
    - **Property 10: _safe_run catches all exceptions**
    - **Validates: Requirements 1.7, 2.5, 3.11**

  - [x] 1.9 Write unit tests for EditFileTool and AppendFileTool (`test_edit.py`)
    - Happy path: successful edit, successful append
    - Edge cases: empty file edit, empty content append, file not found
    - Error conditions: path denied, old_text not found, old_text ambiguous
    - _Requirements: 1.1–1.7, 2.1–2.5_

- [x] 2. Checkpoint — Verify edit tools
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement WebFetchTool
  - [x] 3.1 Create `smartclaw/smartclaw/tools/web_fetch.py` with SSRF guard and HTML extractor
    - Implement `is_private_ip(ip)` function checking loopback, RFC 1918, link-local
    - Implement `check_ssrf(url)` async function validating scheme and resolved IPs
    - Implement `html_to_text(html)` stripping script/style/tags and normalizing whitespace
    - _Requirements: 3.2, 3.3, 3.4_

  - [x] 3.2 Implement `WebFetchTool` class
    - Inherit from `SmartClawTool`, set name/description/args_schema
    - Define `WebFetchInput` with `url: str` and `max_chars: int = 50_000`
    - `_arun` calls `check_ssrf`, fetches via `httpx.AsyncClient`, processes response by content type
    - HTML → `html_to_text`, JSON → `json.dumps(indent=2)`, other → raw text
    - Truncate to `max_chars` with indicator, enforce `max_response_bytes` and `timeout_seconds`
    - Wrap async logic in `_safe_run`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x] 3.3 Write property test: SSRF blocks non-HTTP schemes (`test_web_fetch_props.py`)
    - **Property 5: SSRF guard blocks non-HTTP schemes**
    - **Validates: Requirements 3.2**

  - [x] 3.4 Write property test: SSRF blocks private/local IPs (`test_web_fetch_props.py`)
    - **Property 6: SSRF guard blocks private/local IPs**
    - **Validates: Requirements 3.3**

  - [x] 3.5 Write property test: HTML-to-text strips all tags (`test_web_fetch_props.py`)
    - **Property 7: HTML-to-text strips all tags**
    - **Validates: Requirements 3.4**

  - [x] 3.6 Write property test: JSON formatting round-trip (`test_web_fetch_props.py`)
    - **Property 8: JSON formatting round-trip**
    - **Validates: Requirements 3.5**

  - [x] 3.7 Write property test: text truncation respects max_chars (`test_web_fetch_props.py`)
    - **Property 9: Text truncation respects max_chars**
    - **Validates: Requirements 3.6**

  - [x] 3.8 Write unit tests for WebFetchTool (`test_web_fetch.py`)
    - Happy path: fetch HTML page, fetch JSON endpoint
    - SSRF: blocked schemes, blocked private IPs
    - Error conditions: timeout, oversized response, invalid URL
    - HTML extraction: script/style removal, tag stripping
    - Truncation: content exceeding max_chars
    - _Requirements: 3.1–3.11_

- [x] 4. Checkpoint — Verify web fetch tool
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Registry integration and wiring
  - [x] 5.1 Update `create_system_tools()` in `smartclaw/smartclaw/tools/registry.py`
    - Import `EditFileTool`, `AppendFileTool` from `smartclaw.tools.edit`
    - Import `WebFetchTool` from `smartclaw.tools.web_fetch`
    - Register all 3 new tools, passing `path_policy=policy` to edit/append tools
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 5.2 Write unit tests for registry integration (`test_integration.py` or `test_registry.py`)
    - Verify `create_system_tools()` returns 8 tools total
    - Verify EditFileTool and AppendFileTool share the same PathPolicy instance as existing filesystem tools
    - Verify all expected tool names are present
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 6. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- Each task references specific requirements for traceability
- Property tests validate the 10 correctness properties defined in the design document
- All tools follow the existing `SmartClawTool` → `_safe_run` pattern from `filesystem.py`
- Python is the implementation language (matching the design document)
