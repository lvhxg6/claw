"""Unit tests for WebFetchTool, SSRF guard, and HTML extractor."""

from __future__ import annotations

import ipaddress
from unittest.mock import AsyncMock, patch

from smartclaw.tools.web_fetch import (
    WebFetchTool,
    check_ssrf,
    html_to_text,
    is_private_ip,
)


class TestIsPrivateIP:
    def test_loopback(self) -> None:
        assert is_private_ip(ipaddress.ip_address("127.0.0.1")) is True

    def test_rfc1918_10(self) -> None:
        assert is_private_ip(ipaddress.ip_address("10.0.0.1")) is True

    def test_rfc1918_172(self) -> None:
        assert is_private_ip(ipaddress.ip_address("172.16.0.1")) is True

    def test_rfc1918_192(self) -> None:
        assert is_private_ip(ipaddress.ip_address("192.168.1.1")) is True

    def test_link_local(self) -> None:
        assert is_private_ip(ipaddress.ip_address("169.254.1.1")) is True

    def test_public_ip(self) -> None:
        assert is_private_ip(ipaddress.ip_address("8.8.8.8")) is False

    def test_ipv6_loopback(self) -> None:
        assert is_private_ip(ipaddress.ip_address("::1")) is True


class TestCheckSSRF:
    def test_http_allowed(self) -> None:
        with patch("smartclaw.tools.web_fetch.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 0, "", ("93.184.216.34", 80))]
            assert check_ssrf("https://example.com") is None

    def test_ftp_blocked(self) -> None:
        assert check_ssrf("ftp://example.com") is not None

    def test_file_blocked(self) -> None:
        assert check_ssrf("file:///etc/passwd") is not None

    def test_private_ip_blocked(self) -> None:
        with patch("smartclaw.tools.web_fetch.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 0, "", ("127.0.0.1", 80))]
            result = check_ssrf("http://localhost")
            assert result is not None
            assert "SSRF" in result

    def test_missing_hostname(self) -> None:
        result = check_ssrf("http://")
        assert result is not None


class TestHtmlToText:
    def test_strips_script(self) -> None:
        html = "<html><script>alert(1)</script><body>Hello</body></html>"
        assert "alert" not in html_to_text(html)
        assert "Hello" in html_to_text(html)

    def test_strips_style(self) -> None:
        html = "<style>body{color:red}</style><p>Text</p>"
        result = html_to_text(html)
        assert "color" not in result
        assert "Text" in result

    def test_strips_tags(self) -> None:
        html = "<div><p>Hello <b>World</b></p></div>"
        result = html_to_text(html)
        assert "<" not in result
        assert "Hello" in result
        assert "World" in result


class TestWebFetchTool:
    async def test_ssrf_blocked_scheme(self) -> None:
        tool = WebFetchTool()
        result = await tool._arun(url="ftp://example.com")
        assert "Error:" in result
        assert "HTTP" in result

    async def test_ssrf_blocked_private_ip(self) -> None:
        tool = WebFetchTool()
        with patch("smartclaw.tools.web_fetch.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 0, "", ("192.168.1.1", 80))]
            result = await tool._arun(url="http://internal.corp")
        assert "Error:" in result
        assert "SSRF" in result

    async def test_truncation(self) -> None:
        tool = WebFetchTool()
        long_text = "x" * 100

        mock_resp = AsyncMock()
        mock_resp.content = long_text.encode()
        mock_resp.text = long_text
        mock_resp.headers = {"content-type": "text/plain"}

        with patch("smartclaw.tools.web_fetch.socket.getaddrinfo") as mock_dns, \
             patch("smartclaw.tools.web_fetch.httpx.AsyncClient") as mock_client_cls:
            mock_dns.return_value = [(2, 1, 0, "", ("93.184.216.34", 80))]
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await tool._arun(url="https://example.com", max_chars=50)

        assert "truncated" in result
