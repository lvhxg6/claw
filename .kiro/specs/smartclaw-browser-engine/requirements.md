# Requirements Document

## Introduction

SmartClaw Browser Engine is the core differentiating module (Spec 3, P0 phase) of the SmartClaw AI Agent. It provides a complete browser automation layer built on Playwright and CDP (Chrome DevTools Protocol), enabling the LLM-driven Agent Graph (Spec 2) to understand, interact with, and control web pages. The module covers browser lifecycle management, page understanding via Accessibility Tree parsing, browser actions (click/type/scroll/navigate), screenshot capture, session/tab management, and LangChain Tool integration for the ReAct agent loop.

Reference architecture: Browser Use, OpenClaw `src/browser/` module.

## Glossary

- **Browser_Engine**: The Playwright-based browser lifecycle manager responsible for launching, connecting to, and shutting down browser instances.
- **CDP_Client**: A wrapper around Playwright's native CDPSession for low-level Chrome DevTools Protocol operations (timeout control, network interception, JavaScript evaluation).
- **Page_Parser**: The module that extracts page structure via Playwright's Accessibility Tree (ariaSnapshot) and converts it into LLM-consumable structured text with element references.
- **Action_Executor**: The module that performs browser interactions (click, type, scroll, navigate, select, etc.) on page elements identified by element references or CSS selectors.
- **Screenshot_Capturer**: The module that captures viewport, full-page, or element-level screenshots and encodes them as base64 strings for LLM vision consumption.
- **Session_Manager**: The module that manages browser contexts, tabs (pages), tab switching, and session cleanup including resource reclamation.
- **Browser_Tools**: LangChain Tool wrappers that expose browser actions to the Agent Graph's ReAct loop as callable tools.
- **Element_Reference**: A short identifier (e.g., "e1", "e2") mapped to a specific page element via role and name, generated during Accessibility Tree parsing.
- **A11y_Tree**: The Accessibility Tree representation of a web page, providing a semantic structure of interactive and content elements.
- **Agent_Graph**: The LangGraph ReAct StateGraph from Spec 2 that orchestrates LLM reasoning and tool execution.

## Requirements

### Requirement 1: Browser Engine Lifecycle Management

**User Story:** As a developer, I want the Browser_Engine to manage Playwright browser instances, so that the Agent can launch, connect to, and gracefully shut down browsers.

#### Acceptance Criteria

1. WHEN a headless browser launch is requested, THE Browser_Engine SHALL launch a Chromium browser instance via Playwright with headless mode enabled and return a browser handle within 30 seconds.
2. WHEN a headed browser launch is requested, THE Browser_Engine SHALL launch a Chromium browser instance via Playwright with headless mode disabled and return a browser handle within 30 seconds.
3. WHEN a CDP URL is provided, THE Browser_Engine SHALL connect to the existing browser instance via Playwright `connectOverCDP` and return a browser handle within 10 seconds.
4. WHEN a CDP URL connection fails, THE Browser_Engine SHALL retry up to 3 times with incremental backoff delays before raising a connection error.
5. WHEN shutdown is requested, THE Browser_Engine SHALL close all browser contexts, pages, and the browser instance, and release all associated system resources.
6. IF the browser process becomes unresponsive during shutdown, THEN THE Browser_Engine SHALL force-terminate the browser process after a 10-second timeout.
7. THE Browser_Engine SHALL accept a `BrowserConfig` Pydantic model specifying headless mode, viewport size, proxy settings, user-agent override, and launch arguments.
8. WHILE a browser instance is active, THE Browser_Engine SHALL track the browser connection state and expose an `is_connected` property.

### Requirement 2: CDP Low-Level Operations

**User Story:** As a developer, I want the CDP_Client to provide low-level Chrome DevTools Protocol access, so that the Agent can perform operations not directly exposed by Playwright's high-level API.

#### Acceptance Criteria

1. WHEN a CDPSession is requested for a page, THE CDP_Client SHALL create a CDPSession via Playwright's `page.context().new_cdp_session(page)` and return a session handle.
2. WHEN a CDP command is sent, THE CDP_Client SHALL execute the command with a configurable timeout (default 10 seconds) and return the result.
3. IF a CDP command exceeds the configured timeout, THEN THE CDP_Client SHALL raise a timeout error with the command name and elapsed time.
4. WHEN `Runtime.evaluate` is called, THE CDP_Client SHALL execute the JavaScript expression in the page context and return the result value.
5. WHEN `Page.captureScreenshot` is called via CDP, THE CDP_Client SHALL return the screenshot as a base64-encoded string.
6. WHEN the CDPSession is no longer needed, THE CDP_Client SHALL detach the session to free resources.
7. THE CDP_Client SHALL provide an `execute` method that accepts a CDP domain method name, optional parameters, and an optional timeout override.

### Requirement 3: Page Understanding via Accessibility Tree

**User Story:** As a developer, I want the Page_Parser to extract the Accessibility Tree from a web page, so that the LLM can understand page structure and identify interactive elements.

#### Acceptance Criteria

1. WHEN a page snapshot is requested, THE Page_Parser SHALL extract the Accessibility Tree via Playwright's `page.accessibility.snapshot()` and return a structured text representation.
2. THE Page_Parser SHALL assign sequential Element_References (e.g., "e1", "e2", "e3") to interactive elements (buttons, links, inputs, selects, checkboxes, textboxes) in the snapshot output.
3. THE Page_Parser SHALL assign Element_References to content elements (headings, images, text) that have accessible names.
4. WHEN duplicate role+name combinations exist, THE Page_Parser SHALL append an `[nth=N]` index to distinguish them in the snapshot output.
5. THE Page_Parser SHALL support a `compact` mode that removes unnamed structural elements and empty branches from the output.
6. THE Page_Parser SHALL support an `interactive_only` mode that includes only interactive elements in the output.
7. THE Page_Parser SHALL return both the formatted snapshot text and a mapping of Element_References to their role, name, and nth index.
8. THE Page_Parser SHALL format the snapshot as an indented tree with role names, accessible names in quotes, and `[ref=eN]` annotations.
9. FOR ALL valid page states, parsing then formatting then re-parsing the Element_Reference mapping SHALL produce an equivalent mapping (round-trip property).

### Requirement 4: Browser Actions

**User Story:** As a developer, I want the Action_Executor to perform browser interactions, so that the Agent can navigate, click, type, scroll, and interact with web page elements.

#### Acceptance Criteria

1. WHEN a navigate action is requested with a URL, THE Action_Executor SHALL navigate the current page to the URL and wait for the `load` event within a configurable timeout (default 30 seconds).
2. WHEN a click action is requested with an Element_Reference, THE Action_Executor SHALL resolve the reference to a Playwright locator and click the element within a configurable timeout (default 8 seconds).
3. WHEN a type action is requested with an Element_Reference and text, THE Action_Executor SHALL resolve the reference, fill the text into the element, and optionally press Enter if `submit` is True.
4. WHEN a scroll action is requested with an Element_Reference, THE Action_Executor SHALL scroll the element into the viewport using `scroll_into_view_if_needed`.
5. WHEN a select action is requested with an Element_Reference and values, THE Action_Executor SHALL select the specified option values in the dropdown element.
6. WHEN a go_back action is requested, THE Action_Executor SHALL navigate the page back in history.
7. WHEN a go_forward action is requested, THE Action_Executor SHALL navigate the page forward in history.
8. WHEN a wait action is requested, THE Action_Executor SHALL wait for the specified condition (time delay, text visible, text gone, selector visible, URL match, or load state) within a configurable timeout (default 20 seconds).
9. WHEN a press_key action is requested with a key name, THE Action_Executor SHALL press the specified keyboard key on the page.
10. WHEN a hover action is requested with an Element_Reference, THE Action_Executor SHALL hover over the specified element.
11. IF an action fails due to element not found or timeout, THEN THE Action_Executor SHALL raise a descriptive error including the Element_Reference or selector and the failure reason.
12. THE Action_Executor SHALL clamp all timeout values to a range of 500ms to 60,000ms.

### Requirement 5: Screenshot Capture

**User Story:** As a developer, I want the Screenshot_Capturer to take screenshots of web pages, so that the Agent can use visual understanding as a fallback when the Accessibility Tree is insufficient.

#### Acceptance Criteria

1. WHEN a viewport screenshot is requested, THE Screenshot_Capturer SHALL capture the current viewport and return the image as a base64-encoded PNG string.
2. WHEN a full-page screenshot is requested, THE Screenshot_Capturer SHALL capture the entire scrollable page and return the image as a base64-encoded PNG string.
3. WHEN an element screenshot is requested with an Element_Reference, THE Screenshot_Capturer SHALL capture only the specified element and return the image as a base64-encoded PNG string.
4. THE Screenshot_Capturer SHALL support both PNG and JPEG output formats, with JPEG quality configurable between 0 and 100.
5. WHEN the screenshot exceeds a configurable maximum size (default 5MB), THE Screenshot_Capturer SHALL progressively reduce resolution and JPEG quality until the image fits within the limit.
6. THE Screenshot_Capturer SHALL return a dictionary containing the base64 data, the MIME type, and the image dimensions (width, height).

### Requirement 6: Browser Session and Tab Management

**User Story:** As a developer, I want the Session_Manager to handle multiple browser tabs, so that the Agent can work across multiple pages within a single browser session.

#### Acceptance Criteria

1. WHEN a new tab is requested with a URL, THE Session_Manager SHALL create a new page in the browser context, navigate to the URL, and return a tab identifier.
2. WHEN tab listing is requested, THE Session_Manager SHALL return a list of all open tabs with their identifiers, titles, and URLs.
3. WHEN tab switching is requested with a tab identifier, THE Session_Manager SHALL bring the specified tab to the foreground and set it as the active page.
4. WHEN tab closing is requested with a tab identifier, THE Session_Manager SHALL close the specified page and remove it from the tab registry.
5. IF a tab identifier does not match any open tab, THEN THE Session_Manager SHALL raise a TabNotFoundError with the requested identifier.
6. WHEN session cleanup is requested, THE Session_Manager SHALL close all tabs, close the browser context, and clear all internal state.
7. THE Session_Manager SHALL maintain a mapping of tab identifiers to Playwright Page objects and expose the currently active tab.
8. WHILE a browser session is active, THE Session_Manager SHALL track console messages, page errors, and network requests per tab with configurable buffer limits (default 500 console messages, 200 errors, 500 network requests).

### Requirement 7: Browser Tools Integration with Agent Graph

**User Story:** As a developer, I want browser actions exposed as LangChain Tools, so that the Agent Graph can invoke browser operations through the ReAct tool-calling loop.

#### Acceptance Criteria

1. THE Browser_Tools module SHALL provide a `navigate` tool that accepts a URL string and returns the page title and URL after navigation.
2. THE Browser_Tools module SHALL provide a `click` tool that accepts an Element_Reference string and returns a confirmation message.
3. THE Browser_Tools module SHALL provide a `type_text` tool that accepts an Element_Reference string, text content, and an optional submit flag, and returns a confirmation message.
4. THE Browser_Tools module SHALL provide a `scroll` tool that accepts an Element_Reference string and returns a confirmation message.
5. THE Browser_Tools module SHALL provide a `screenshot` tool that accepts an optional full_page flag and returns the base64-encoded image data.
6. THE Browser_Tools module SHALL provide a `get_page_snapshot` tool that returns the Accessibility Tree snapshot text of the current page.
7. THE Browser_Tools module SHALL provide a `go_back` tool and a `go_forward` tool for history navigation.
8. THE Browser_Tools module SHALL provide a `wait` tool that accepts wait conditions (time, text, selector, URL, load_state) and returns a confirmation message.
9. THE Browser_Tools module SHALL provide a `select_option` tool that accepts an Element_Reference and a list of values.
10. THE Browser_Tools module SHALL provide a `press_key` tool that accepts a key name string.
11. THE Browser_Tools module SHALL provide a `switch_tab` tool that accepts a tab identifier and returns the new active tab information.
12. THE Browser_Tools module SHALL provide a `list_tabs` tool that returns all open tabs with their identifiers, titles, and URLs.
13. THE Browser_Tools module SHALL provide a `new_tab` tool that accepts a URL and returns the new tab identifier and metadata.
14. THE Browser_Tools module SHALL provide a `close_tab` tool that accepts a tab identifier.
15. WHEN any browser tool encounters an error, THE Browser_Tools module SHALL return a human-readable error message as the tool result instead of raising an exception.
16. THE Browser_Tools module SHALL provide a `get_all_browser_tools()` function that returns a list of all browser LangChain Tool instances for registration with the Agent Graph.

### Requirement 8: Resource Management and Error Handling

**User Story:** As a developer, I want robust resource management, so that browser processes and memory are properly cleaned up even when errors occur.

#### Acceptance Criteria

1. THE Browser_Engine SHALL implement Python async context manager protocol (`__aenter__` / `__aexit__`) for automatic resource cleanup.
2. WHEN an unhandled exception occurs during browser operations, THE Browser_Engine SHALL log the error via structlog and attempt graceful cleanup before re-raising.
3. THE Session_Manager SHALL implement Python async context manager protocol for automatic session cleanup.
4. IF a page becomes unresponsive, THEN THE Action_Executor SHALL raise a timeout error after the configured timeout and allow the caller to decide on recovery.
5. THE Browser_Engine SHALL log all lifecycle events (launch, connect, disconnect, shutdown) via structlog with structured context fields.
6. THE Browser_Engine SHALL accept a configurable maximum number of concurrent pages (default 10) and reject new tab creation when the limit is reached.
