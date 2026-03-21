"""Tests for shell exec internal URL blocking."""

from __future__ import annotations

import socket
from unittest.mock import patch

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

