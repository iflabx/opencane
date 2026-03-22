"""Tests for web_fetch SSRF protection and untrusted content marking."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import pytest

from opencane.agent.tools.web import WebFetchTool


def _fake_resolve_private(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
    del hostname, port, family, type_
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
    del hostname, port, family, type_
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_ip() -> None:
    tool = WebFetchTool()
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(url="http://169.254.169.254/computeMetadata/v1/")
    data = json.loads(result)
    assert "error" in data
    assert "private" in data["error"].lower() or "blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_result_contains_untrusted_flag() -> None:
    tool = WebFetchTool()

    class FakeResponse:
        status_code = 200
        url = "https://example.com/api"
        text = "{}"
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self):  # type: ignore[no-untyped-def]
            return {"ok": True}

    async def _fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        del self, url, kwargs
        return FakeResponse()

    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public), patch(
        "httpx.AsyncClient.get", _fake_get
    ):
        result = await tool.execute(url="https://example.com/api")

    data = json.loads(result)
    assert data.get("untrusted") is True
    assert "[External content" in data.get("text", "")


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_redirect_target() -> None:
    tool = WebFetchTool()

    class FakeResponse:
        status_code = 200
        url = "http://127.0.0.1/secret"
        text = '{"ok": true}'
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self):  # type: ignore[no-untyped-def]
            return {"ok": True}

    async def _fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        del self, url, kwargs
        return FakeResponse()

    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public), patch(
        "httpx.AsyncClient.get", _fake_get
    ):
        result = await tool.execute(url="https://example.com/redirect")

    data = json.loads(result)
    assert "error" in data
    assert "redirect blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_returns_multimodal_blocks_for_image() -> None:
    tool = WebFetchTool()

    class FakeStreamResponse:
        status_code = 200
        headers = {"content-type": "image/png"}
        url = "https://example.com/image.png"

        def __init__(self) -> None:
            self.content = b"\x89PNG\r\n\x1a\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aread(self):
            return self.content

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):  # type: ignore[no-untyped-def]
            del method, url, headers
            return FakeStreamResponse()

        async def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            del url, kwargs
            raise AssertionError("should not fallback to text fetch when image prefetch succeeds")

    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public), patch(
        "opencane.agent.tools.web.httpx.AsyncClient", FakeClient
    ):
        result = await tool.execute(url="https://example.com/image.png")

    assert isinstance(result, list)
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result[0]["_meta"]["path"] == "https://example.com/image.png"
    assert result[1]["text"] == "(Image fetched from: https://example.com/image.png)"


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_redirect_before_returning_image() -> None:
    tool = WebFetchTool()

    class FakeStreamResponse:
        headers = {"content-type": "image/png"}
        url = "http://127.0.0.1/secret.png"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aread(self):
            return b"\x89PNG\r\n\x1a\n"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):  # type: ignore[no-untyped-def]
            del method, url, headers
            return FakeStreamResponse()

    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public), patch(
        "opencane.agent.tools.web.httpx.AsyncClient", FakeClient
    ):
        result = await tool.execute(url="https://example.com/image.png")

    data = json.loads(result)
    assert "error" in data
    assert "redirect blocked" in data["error"].lower()
