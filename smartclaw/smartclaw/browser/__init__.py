"""SmartClaw Browser Engine — public API.

Exports the core browser automation components.
"""

from smartclaw.browser.actions import ActionExecutor
from smartclaw.browser.cdp import CDPClient
from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.exceptions import (
    ActionTimeoutError,
    BrowserConnectionError,
    BrowserLaunchError,
    CDPEvaluateError,
    CDPSessionError,
    CDPTimeoutError,
    ElementNotFoundError,
    ElementNotVisibleError,
    MaxPagesExceededError,
    NavigationError,
    ScreenshotTooLargeError,
    TabNotFoundError,
)
from smartclaw.browser.page_parser import (
    CONTENT_ROLES,
    INTERACTIVE_ROLES,
    STRUCTURAL_ROLES,
    PageParser,
    RoleRef,
    RoleRefMap,
    SnapshotResult,
)
from smartclaw.browser.screenshot import ScreenshotCapturer
from smartclaw.browser.session import (
    ConsoleEntry,
    ErrorEntry,
    NetworkEntry,
    SessionManager,
    TabInfo,
    TabState,
)

__all__ = [
    # Engine
    "BrowserConfig",
    "BrowserEngine",
    # CDP
    "CDPClient",
    # Page Parser
    "PageParser",
    "RoleRef",
    "RoleRefMap",
    "SnapshotResult",
    "INTERACTIVE_ROLES",
    "CONTENT_ROLES",
    "STRUCTURAL_ROLES",
    # Actions
    "ActionExecutor",
    # Screenshot
    "ScreenshotCapturer",
    # Session
    "SessionManager",
    "TabInfo",
    "TabState",
    "ConsoleEntry",
    "ErrorEntry",
    "NetworkEntry",
    # Exceptions
    "BrowserLaunchError",
    "BrowserConnectionError",
    "CDPTimeoutError",
    "CDPSessionError",
    "CDPEvaluateError",
    "ElementNotFoundError",
    "ActionTimeoutError",
    "NavigationError",
    "ScreenshotTooLargeError",
    "ElementNotVisibleError",
    "TabNotFoundError",
    "MaxPagesExceededError",
]
