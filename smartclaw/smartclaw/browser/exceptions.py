"""Custom exception classes for the SmartClaw browser engine."""

from __future__ import annotations


class BrowserLaunchError(Exception):
    """Browser failed to launch within the timeout."""

    def __init__(self, headless: bool, timeout: float, cause: str = "") -> None:
        self.headless = headless
        self.timeout = timeout
        self.cause = cause
        mode = "headless" if headless else "headed"
        msg = f"Failed to launch {mode} browser within {timeout}s"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


class BrowserConnectionError(Exception):
    """Failed to connect to browser via CDP after retries."""

    def __init__(self, cdp_url: str, retries: int, errors: list[str] | None = None) -> None:
        self.cdp_url = cdp_url
        self.retries = retries
        self.errors = errors or []
        msg = f"Failed to connect to {cdp_url} after {retries} retries"
        if self.errors:
            msg += f": {'; '.join(self.errors)}"
        super().__init__(msg)


class CDPTimeoutError(Exception):
    """CDP command exceeded the configured timeout."""

    def __init__(self, method: str, elapsed: float) -> None:
        self.method = method
        self.elapsed = elapsed
        super().__init__(f"CDP command '{method}' timed out after {elapsed:.1f}s")


class CDPSessionError(Exception):
    """Failed to create a CDPSession."""

    def __init__(self, page_url: str, cause: str = "") -> None:
        self.page_url = page_url
        self.cause = cause
        msg = f"Failed to create CDPSession for page '{page_url}'"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


class CDPEvaluateError(Exception):
    """JavaScript evaluation via CDP failed."""

    def __init__(self, expression: str, cause: str = "") -> None:
        self.expression = expression[:100]
        self.cause = cause
        msg = f"CDP evaluate failed for '{self.expression}'"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


class ElementNotFoundError(Exception):
    """Element reference could not be resolved on the page."""

    def __init__(self, ref: str, cause: str = "") -> None:
        self.ref = ref
        self.cause = cause
        msg = f"Element '{ref}' not found"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


class ActionTimeoutError(Exception):
    """A browser action exceeded the configured timeout."""

    def __init__(self, action: str, ref_or_selector: str, timeout_ms: int) -> None:
        self.action = action
        self.ref_or_selector = ref_or_selector
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Action '{action}' on '{ref_or_selector}' timed out after {timeout_ms}ms"
        )


class NavigationError(Exception):
    """Page navigation failed."""

    def __init__(self, url: str, cause: str = "") -> None:
        self.url = url
        self.cause = cause
        msg = f"Navigation to '{url}' failed"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


class ScreenshotTooLargeError(Exception):
    """Screenshot exceeds the maximum allowed size after quality reduction."""

    def __init__(self, actual_bytes: int, max_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Screenshot size {actual_bytes} bytes exceeds limit of {max_bytes} bytes"
        )


class ElementNotVisibleError(Exception):
    """Element is not visible for screenshot capture."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        super().__init__(f"Element '{ref}' is not visible for screenshot")


class TabNotFoundError(Exception):
    """Specified tab identifier does not exist."""

    def __init__(self, tab_id: str) -> None:
        self.tab_id = tab_id
        super().__init__(f"Tab '{tab_id}' not found")


class MaxPagesExceededError(Exception):
    """Attempted to create more pages than the configured limit."""

    def __init__(self, current: int, limit: int) -> None:
        self.current = current
        self.limit = limit
        super().__init__(
            f"Cannot create new page: {current} pages open, limit is {limit}"
        )
