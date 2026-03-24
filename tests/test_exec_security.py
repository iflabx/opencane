"""Tests for shell exec internal URL blocking."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from opencane.agent.tools.shell import ExecTool


def _fake_resolve_private(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
    del hostname, port, family, type_
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
    del hostname, port, family, type_
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def test_exec_guard_blocks_internal_url() -> None:
    tool = ExecTool()
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_private):
        error = tool._guard_command("curl http://169.254.169.254/latest/meta-data", "/tmp")
    assert error is not None
    assert "internal/private URL" in error


def test_exec_guard_allows_public_url() -> None:
    tool = ExecTool()
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public):
        error = tool._guard_command("curl https://example.com", "/tmp")
    assert error is None


def test_exec_guard_allows_url_query_with_format_parameter() -> None:
    tool = ExecTool()
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public):
        error = tool._guard_command("curl -s 'https://example.com/weather?format=3'", "/tmp")
    assert error is None


def test_exec_guard_allows_post_body_with_format_field() -> None:
    tool = ExecTool()
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve_public):
        error = tool._guard_command("curl -d 'format=json' https://example.com/post", "/tmp")
    assert error is None


def test_exec_guard_blocks_standalone_format_command() -> None:
    tool = ExecTool()
    error = tool._guard_command("echo hi; format c:", "/tmp")
    assert error is not None
    assert "blocked by safety guard" in error


@pytest.mark.asyncio
async def test_exec_tool_appends_path_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_env: dict[str, str] = {}

    class _FakeProcess:
        returncode = 0

        async def communicate(self):  # type: ignore[no-untyped-def]
            return b"ok", b""

    async def _fake_create_subprocess_shell(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        env = kwargs.get("env") or {}
        if isinstance(env, dict):
            captured_env.update({k: str(v) for k, v in env.items() if isinstance(k, str)})
        return _FakeProcess()

    monkeypatch.setattr("opencane.agent.tools.shell.asyncio.create_subprocess_shell", _fake_create_subprocess_shell)
    tool = ExecTool(path_append="/usr/sbin")

    result = await tool.execute("echo ok")
    assert "ok" in result
    assert "PATH" in captured_env
    assert captured_env["PATH"].endswith("/usr/sbin")
