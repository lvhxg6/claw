# Implementation Plan: SmartClaw Browser Engine

## Overview

Implement the browser automation engine (Spec 3) for SmartClaw. The module is built on Playwright (async API) + CDP, providing browser lifecycle management, Accessibility Tree page understanding, browser actions, screenshot capture, session/tab management, and LangChain Tool integration for the Agent Graph ReAct loop.

All new code lives under `smartclaw/smartclaw/browser/` and `smartclaw/smartclaw/tools/browser_tools.py`, with tests under `smartclaw/tests/browser/` and `smartclaw/tests/tools/`.

## Tasks

- [x] 1. Project setup and dependencies
  - [x] 1.1 Add `playwright` to `pyproject.toml` dependencies and `pytest-playwright` to dev dependencies
    - Add `playwright` to `[project.dependencies]`
    - Add `pytest-playwright` to `[project.optional-dependencies] dev`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Create `smartclaw/smartclaw/browser/__init__.py` package and `smartclaw/smartclaw/tools/__init__.py` package
    - Create empty `__init__.py` files for both new packages
    - Create `smartclaw/tests/browser/__init__.py`
    - _Requirements: N/A (scaffolding)_

  - [x] 1.3 Define custom exception classes in `smartclaw/smartclaw/browser/exceptions.py`
    - Implement `BrowserLaunchError`, `BrowserConnectionError`, `CDPTimeoutError`, `CDPSessionError`, `CDPEvaluateError`, `ElementNotFoundError`, `ActionTimeoutError`, `NavigationError`, `ScreenshotTooLargeError`, `ElementNotVisibleError`, `TabNotFoundError`, `MaxPagesExceededError`
    - Each exception should include descriptive context fields as specified in the design error handling section
    - _Requirements: 4.11, 6.5, 8.6_

- [x] 2. BrowserConfig data model and BrowserEngine lifecycle
  - [x] 2.1 Implement `BrowserConfig` Pydantic model in `smartclaw/smartclaw/browser/engine.py`
    - Fields: `headless`, `viewport_width`, `viewport_height`, `proxy`, `user_agent`, `launch_args`, `max_pages` with validators as specified in design
    - _Requirements: 1.7_

  - [x] 2.2 Write property test for BrowserConfig (Property 1)
    - **Property 1: BrowserConfig accepts all valid configurations**
    - Test that any valid combination of fields constructs successfully and preserves values
    - Use hypothesis strategies: `st.booleans()`, `st.integers(1, 4096)`, `st.text()`, `st.none() | st.text()`, `st.lists(st.text())`, `st.integers(1, 100)`
    - File: `smartclaw/tests/browser/test_engine_props.py`
    - **Validates: Requirements 1.7**

  - [x] 2.3 Implement `BrowserEngine` class in `smartclaw/smartclaw/browser/engine.py`
    - Implement `__init__`, `is_connected` property, `launch()` (headless/headed via config, 30s timeout), `connect(cdp_url)` (10s timeout, 3 retries with incremental backoff), `shutdown()` (close all contexts/pages/browser, force-kill after 10s if unresponsive)
    - Implement `__aenter__` / `__aexit__` async context manager protocol
    - Log all lifecycle events via structlog
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 8.1, 8.2, 8.5_

  - [x] 2.4 Write property test for browser connection state (Property 2)
    - **Property 2: Browser connection state round-trip**
    - After launch() → is_connected is True; after shutdown() → is_connected is False
    - Use AsyncMock for Playwright, `st.booleans()` for headless
    - File: `smartclaw/tests/browser/test_engine_props.py`
    - **Validates: Requirements 1.8**

  - [x] 2.5 Write unit tests for BrowserEngine
    - Test headless/headed launch (1.1, 1.2), CDP connect (1.3), retry logic (1.4), shutdown cleanup (1.5), force-terminate (1.6), context manager (8.1), lifecycle logging (8.5), exception cleanup (8.2)
    - File: `smartclaw/tests/browser/test_engine.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 8.1, 8.2, 8.5_

  - [x] 2.6 Extend `SmartClawSettings` in `smartclaw/smartclaw/config/settings.py` to include `browser: BrowserConfig`
    - Import BrowserConfig and add field with default_factory
    - _Requirements: 1.7_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. CDP Client
  - [x] 4.1 Implement `CDPClient` class in `smartclaw/smartclaw/browser/cdp.py`
    - Implement `__init__(page)`, `create_session()` via `page.context().new_cdp_session(page)`, `execute(method, params, timeout)` with configurable timeout (default 10s), `evaluate_js(expression)` via `Runtime.evaluate`, `capture_screenshot()` via `Page.captureScreenshot`, `detach()` to free resources
    - Raise `CDPTimeoutError` on timeout, `CDPSessionError` on session creation failure, `CDPEvaluateError` on JS execution failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 4.2 Write unit tests for CDPClient
    - Test CDPSession creation (2.1), command execution (2.2), timeout error (2.3), JS evaluation (2.4), CDP screenshot (2.5), session detach (2.6), execute API (2.7)
    - Use AsyncMock for Playwright Page and CDPSession
    - File: `smartclaw/tests/browser/test_cdp.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 5. Page Parser and Accessibility Tree
  - [x] 5.1 Implement role classification constants and data models in `smartclaw/smartclaw/browser/page_parser.py`
    - Define `INTERACTIVE_ROLES`, `CONTENT_ROLES`, `STRUCTURAL_ROLES` frozensets
    - Implement `RoleRef` frozen dataclass, `RoleRefMap` type alias, `SnapshotResult` dataclass
    - _Requirements: 3.2, 3.3_

  - [x] 5.2 Implement `PageParser` class in `smartclaw/smartclaw/browser/page_parser.py`
    - Implement `snapshot(page, compact, interactive_only)` method: extract A11y tree via `page.accessibility.snapshot()`, assign sequential `eN` refs to interactive elements and named content elements, handle duplicate role+name with `[nth=N]`, format as indented tree with `[ref=eN]` annotations
    - Implement `resolve_ref(ref)` static method supporting `e1`, `@e1`, `ref=e1` formats
    - Return `SnapshotResult` with formatted text and `RoleRefMap`
    - Handle None snapshot (return empty snapshot)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 5.3 Write property test for snapshot refs consistency (Property 3)
    - **Property 3: Snapshot refs consistency**
    - Every `[ref=eN]` in text has a refs map entry and vice versa; all interactive elements have refs; all named content elements have refs
    - Use custom A11y tree hypothesis generator
    - File: `smartclaw/tests/browser/test_parser_props.py`
    - **Validates: Requirements 3.2, 3.3, 3.7, 3.8**

  - [x] 5.4 Write property test for duplicate role+name disambiguation (Property 4)
    - **Property 4: Duplicate role+name disambiguation**
    - Duplicate role+name elements get distinct `[nth=N]` indices starting from 0, sequential
    - File: `smartclaw/tests/browser/test_parser_props.py`
    - **Validates: Requirements 3.4**

  - [x] 5.5 Write property test for compact mode (Property 5)
    - **Property 5: Compact mode excludes unnamed structural elements**
    - With compact=True, no unnamed structural-role elements appear unless they have descendants with refs
    - File: `smartclaw/tests/browser/test_parser_props.py`
    - **Validates: Requirements 3.5**

  - [x] 5.6 Write property test for interactive-only mode (Property 6)
    - **Property 6: Interactive-only mode filters non-interactive elements**
    - With interactive_only=True, every element in output has a role in INTERACTIVE_ROLES
    - File: `smartclaw/tests/browser/test_parser_props.py`
    - **Validates: Requirements 3.6**

  - [x] 5.7 Write property test for Element Reference mapping round-trip (Property 7)
    - **Property 7: Element Reference mapping round-trip**
    - Parse tree → SnapshotResult → re-parse snapshot text → equivalent RoleRefMap
    - File: `smartclaw/tests/browser/test_parser_props.py`
    - **Validates: Requirements 3.9**

  - [x] 5.8 Write unit tests for PageParser
    - Test empty page snapshot (3.1), specific page snapshot examples, role classification verification
    - File: `smartclaw/tests/browser/test_parser.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [-] 7. Action Executor
  - [ ] 7.1 Implement `_clamp_timeout` function and `ActionExecutor` class in `smartclaw/smartclaw/browser/actions.py`
    - Implement `_clamp_timeout(timeout_ms, default)` clamping to [500, 60000]
    - Implement `ActionExecutor` with `set_ref_map`, `_resolve_locator` (ref → getByRole + nth), and all action methods: `navigate`, `click`, `type_text`, `scroll`, `select`, `go_back`, `go_forward`, `press_key`, `hover`, `wait` (time/text/text_gone/selector/url/load_state conditions)
    - Raise `ElementNotFoundError` with ref string on element not found, `ActionTimeoutError` on timeout
    - Log actions via structlog
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_

  - [ ] 7.2 Write property test for timeout clamping (Property 9)
    - **Property 9: Timeout clamping bounds**
    - For any integer, `_clamp_timeout` returns value in [500, 60000]; below 500 → 500, above 60000 → 60000, within range → preserved
    - Use `st.integers(-100000, 200000)`
    - File: `smartclaw/tests/browser/test_actions_props.py`
    - **Validates: Requirements 4.12**

  - [ ] 7.3 Write property test for action error messages (Property 8)
    - **Property 8: Action error messages include element reference**
    - For any `eN` ref string used in a failed action, the error message contains the original ref string
    - Use `st.from_regex(r'e\d+', fullmatch=True)` for refs
    - File: `smartclaw/tests/browser/test_actions_props.py`
    - **Validates: Requirements 4.11**

  - [ ] 7.4 Write unit tests for ActionExecutor
    - Test navigate (4.1), click (4.2), type_text (4.3), scroll (4.4), select (4.5), go_back (4.6), go_forward (4.7), wait conditions (4.8), press_key (4.9), hover (4.10), page unresponsive timeout (8.4)
    - Use AsyncMock for Playwright Page and Locator
    - File: `smartclaw/tests/browser/test_actions.py`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 8.4_

- [ ] 8. Screenshot Capturer
  - [ ] 8.1 Implement `ScreenshotResult` dataclass and `ScreenshotCapturer` class in `smartclaw/smartclaw/browser/screenshot.py`
    - Implement `capture_viewport`, `capture_full_page`, `capture_element` methods
    - Support PNG and JPEG formats with configurable JPEG quality [0, 100]
    - Implement progressive quality reduction when screenshot exceeds `max_bytes` (default 5MB)
    - Return `ScreenshotResult` with base64 data, MIME type, width, height
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ] 8.2 Write property test for screenshot result completeness (Property 10)
    - **Property 10: Screenshot result completeness**
    - For any successful capture: non-empty base64 data, mime_type is "image/png" or "image/jpeg", width and height are positive integers, JPEG quality clamped to [0, 100]
    - Use `st.sampled_from(["png", "jpeg"])`, `st.integers(0, 100)` for quality
    - File: `smartclaw/tests/browser/test_screenshot_props.py`
    - **Validates: Requirements 5.4, 5.6**

  - [ ] 8.3 Write unit tests for ScreenshotCapturer
    - Test viewport screenshot (5.1), full-page screenshot (5.2), element screenshot (5.3), progressive quality reduction (5.5)
    - Use AsyncMock for Playwright Page, return pre-made small PNG base64
    - File: `smartclaw/tests/browser/test_screenshot.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Session Manager and Tab Management
  - [ ] 10.1 Implement `TabInfo`, `TabState`, event entry dataclasses, and `TabNotFoundError` in `smartclaw/smartclaw/browser/session.py`
    - Implement `TabInfo`, `ConsoleEntry`, `ErrorEntry`, `NetworkEntry`, `TabState` dataclasses
    - `TabState` uses `deque` with configurable maxlen (500 console, 200 errors, 500 network)
    - _Requirements: 6.2, 6.7, 6.8_

  - [ ] 10.2 Implement `SessionManager` class in `smartclaw/smartclaw/browser/session.py`
    - Implement `__init__(engine)`, `active_tab_id`, `active_page` properties
    - Implement `new_tab(url)` — create page, navigate, register tab, enforce max_pages limit, attach event listeners for console/errors/network
    - Implement `list_tabs()`, `switch_tab(tab_id)`, `close_tab(tab_id)`, `cleanup()`
    - Implement `__aenter__` / `__aexit__` async context manager protocol
    - Raise `TabNotFoundError` for invalid tab_id, `MaxPagesExceededError` when limit reached
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 8.3, 8.6_

  - [ ] 10.3 Write property test for tab registry consistency (Property 11)
    - **Property 11: Tab registry consistency**
    - For any sequence of new_tab/close_tab, list_tabs() returns exactly created-but-not-closed tabs; active_page corresponds to a tab in the list or is None
    - Use `st.lists(st.sampled_from(["new", "close"]))` for operation sequences
    - File: `smartclaw/tests/browser/test_session_props.py`
    - **Validates: Requirements 6.2, 6.4, 6.7**

  - [ ] 10.4 Write property test for tab switching (Property 12)
    - **Property 12: Tab switching sets active tab**
    - After switch_tab(tab_id), active_tab_id equals that tab_id
    - File: `smartclaw/tests/browser/test_session_props.py`
    - **Validates: Requirements 6.3**

  - [ ] 10.5 Write property test for invalid tab identifier (Property 13)
    - **Property 13: Invalid tab identifier raises TabNotFoundError**
    - Any string not in the registry raises TabNotFoundError with the identifier in the message
    - Use `st.text().filter(lambda s: not s.startswith("tab_"))` for invalid IDs
    - File: `smartclaw/tests/browser/test_session_props.py`
    - **Validates: Requirements 6.5**

  - [ ] 10.6 Write property test for event buffer limits (Property 14)
    - **Property 14: Event buffer respects size limits**
    - For N > 500 console messages, deque contains at most 500 (most recent); same for errors (200) and network (500)
    - Use `st.integers(1, 2000)` for message count
    - File: `smartclaw/tests/browser/test_session_props.py`
    - **Validates: Requirements 6.8**

  - [ ] 10.7 Write property test for max concurrent pages (Property 16)
    - **Property 16: Max concurrent pages enforcement**
    - With max_pages=N, after creating N tabs, tab N+1 is rejected with error
    - Use `st.integers(1, 20)` for max_pages
    - File: `smartclaw/tests/browser/test_session_props.py`
    - **Validates: Requirements 8.6**

  - [ ] 10.8 Write unit tests for SessionManager
    - Test new tab creation (6.1), session cleanup (6.6), context manager (8.3)
    - File: `smartclaw/tests/browser/test_session.py`
    - _Requirements: 6.1, 6.6, 8.3_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Browser Tools LangChain integration
  - [ ] 12.1 Implement `_safe_tool_call` helper and all 14 browser LangChain Tools in `smartclaw/smartclaw/tools/browser_tools.py`
    - Implement `_safe_tool_call` wrapper that catches exceptions and returns human-readable error strings
    - Implement tools: `navigate`, `click`, `type_text`, `scroll`, `screenshot`, `get_page_snapshot`, `go_back`, `go_forward`, `wait`, `select_option`, `press_key`, `switch_tab`, `list_tabs`, `new_tab`, `close_tab`
    - Each tool extends LangChain `BaseTool` with proper name, description, and args_schema
    - Implement `get_all_browser_tools(session, parser, actions, capturer)` returning all 14+ tool instances
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 7.14, 7.15, 7.16_

  - [ ] 12.2 Write property test for browser tools exception handling (Property 15)
    - **Property 15: Browser tools catch exceptions and return error strings**
    - For any tool invocation that raises an exception, the tool returns a string error message instead of propagating
    - Use `st.sampled_from(EXCEPTION_TYPES)`, `st.text()` for error messages
    - File: `smartclaw/tests/browser/test_tools_props.py`
    - **Validates: Requirements 7.15**

  - [ ] 12.3 Write unit tests for Browser Tools
    - Test all 14 tools exist and return correct format (7.1-7.14), `get_all_browser_tools` returns correct count (7.16)
    - File: `smartclaw/tests/browser/test_tools.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 7.14, 7.16_

- [ ] 13. Wire browser tools into Agent Graph
  - [ ] 13.1 Register browser tools in the Agent Graph build pipeline
    - Update `smartclaw/smartclaw/agent/graph.py` or create a helper to instantiate BrowserEngine, SessionManager, PageParser, ActionExecutor, ScreenshotCapturer, and call `get_all_browser_tools()` to produce the tool list for `build_graph`
    - Ensure browser tools are available alongside any existing tools
    - _Requirements: 7.16_

  - [ ] 13.2 Add `browser/__init__.py` public exports
    - Export `BrowserEngine`, `BrowserConfig`, `CDPClient`, `PageParser`, `ActionExecutor`, `ScreenshotCapturer`, `SessionManager` and key data models from `smartclaw/smartclaw/browser/__init__.py`
    - _Requirements: N/A (wiring)_

- [ ] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- Each property test must run at least 100 iterations (`@settings(max_examples=100)`)
- Each property test must include the annotation comment: `# Feature: smartclaw-browser-engine, Property {N}: {title}`
- All Playwright interactions use AsyncMock in unit/property tests (no real browser needed)
- Integration tests with real browsers are out of scope for this task list (marked `@pytest.mark.integration` in design)
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- All requirements (1.1–8.6) are covered by implementation and test tasks
