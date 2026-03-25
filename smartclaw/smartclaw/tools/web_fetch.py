"""WebFetchTool — fetch URL content with SSRF protection and HTML-to-text.

Provides:
- ``is_private_ip`` — check if IP is private/loopback/link-local
- ``check_ssrf`` — validate URL against SSRF rules
- ``html_to_text`` — strip HTML tags and extract readable text
- ``WebFetchTool`` — LangChain tool for fetching web content
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from smartclaw.tools.base import SmartClawTool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CHARS = 50_000
_DEFAULT_TIMEOUT_S = 60
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TRUNCATION_SUFFIX = "\n\n... [truncated — content exceeds max_chars limit]"

# Pre-compiled regexes for HTML text extraction
_RE_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_RE_STYLE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"[^\S\n]+")
_RE_BLANK_LINES = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# SSRF Guard
# ---------------------------------------------------------------------------


def is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *ip* is loopback, private, link-local, or reserved."""
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved


def check_ssrf(url: str) -> str | None:
    """Validate *url* against SSRF rules.

    Returns an error message string if blocked, ``None`` if safe.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return "Only HTTP and HTTPS URLs are allowed"

    hostname = parsed.hostname
    if not hostname:
        return "Missing hostname in URL"

    # Resolve hostname to IPs
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Failed to resolve hostname: {hostname}"

    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if is_private_ip(ip):
            return "URL points to a private/local network address (SSRF blocked)"

    return None


# ---------------------------------------------------------------------------
# HTML-to-Text
# ---------------------------------------------------------------------------


def html_to_text(html: str) -> str:
    """Strip script/style tags, remove HTML tags, normalize whitespace."""
    text = _RE_SCRIPT.sub("", html)
    text = _RE_STYLE.sub("", text)
    text = _RE_TAGS.sub("", text)
    text = _RE_WHITESPACE.sub(" ", text)
    text = _RE_BLANK_LINES.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class WebFetchInput(BaseModel):
    url: str = Field(description="URL to fetch (HTTP or HTTPS only)")
    max_chars: int = Field(default=_DEFAULT_MAX_CHARS, description="Maximum characters to return")


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


class WebFetchTool(SmartClawTool):
    """Fetch a web page and return its content as readable text."""

    name: str = "web_fetch"
    description: str = "Fetch a URL and extract readable content (HTML to text). Use this to get articles, documentation, or any web content."
    args_schema: type[BaseModel] = WebFetchInput

    timeout_seconds: int = _DEFAULT_TIMEOUT_S
    max_response_bytes: int = _DEFAULT_MAX_BYTES

    async def _arun(self, url: str, max_chars: int = _DEFAULT_MAX_CHARS, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            # SSRF check
            ssrf_error = check_ssrf(url)
            if ssrf_error:
                return f"Error: {ssrf_error}"

            # Fetch
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    max_redirects=5,
                ) as client:
                    resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
            except httpx.TimeoutException:
                return f"Error: Request timed out after {self.timeout_seconds} seconds"
            except httpx.HTTPError as e:
                return f"Error: Failed to fetch URL — {e}"

            # Size check
            if len(resp.content) > self.max_response_bytes:
                return f"Error: Response size exceeds {self.max_response_bytes} bytes limit"

            body = resp.text
            content_type = resp.headers.get("content-type", "")

            # Process by content type
            if "text/html" in content_type:
                text = html_to_text(body)
            elif "application/json" in content_type:
                try:
                    parsed = json.loads(body)
                    text = json.dumps(parsed, indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    text = body
            else:
                text = body

            # Truncate
            if len(text) > max_chars:
                text = text[:max_chars] + TRUNCATION_SUFFIX

            return text

        return await self._safe_run(_do())
