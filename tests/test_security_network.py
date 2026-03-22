"""Tests for opencane.security.network SSRF guardrails."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from opencane.security.network import contains_internal_url, validate_url_target


def _fake_resolve(host: str, results: list[str]):  # type: ignore[no-untyped-def]
    def _resolver(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")

    return _resolver


def test_rejects_non_http_scheme() -> None:
    ok, err = validate_url_target("ftp://example.com/file")
    assert not ok
    assert "http" in err.lower()


def test_rejects_missing_domain() -> None:
    ok, _ = validate_url_target("http://")
    assert not ok


@pytest.mark.parametrize(
    ("ip", "label"),
    [
        ("127.0.0.1", "loopback"),
        ("10.0.0.1", "rfc1918_10"),
        ("172.16.5.1", "rfc1918_172"),
        ("192.168.1.1", "rfc1918_192"),
        ("169.254.169.254", "metadata"),
        ("0.0.0.0", "zero"),
    ],
)
def test_blocks_private_ipv4(ip: str, label: str) -> None:
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve("evil.com", [ip])):
        ok, err = validate_url_target("http://evil.com/path")
    assert not ok, f"Should block {label} ({ip})"
    assert "private" in err.lower() or "blocked" in err.lower()


def test_blocks_ipv6_loopback() -> None:
    def _resolver(hostname, port, family=0, type_=0):  # type: ignore[no-untyped-def]
        del hostname, port, family, type_
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]

    with patch("opencane.security.network.socket.getaddrinfo", _resolver):
        ok, _ = validate_url_target("http://evil.com/")
    assert not ok


def test_allows_public_ip() -> None:
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        ok, err = validate_url_target("http://example.com/page")
    assert ok, err


def test_detects_internal_url_in_command() -> None:
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve("localhost", ["127.0.0.1"])):
        assert contains_internal_url("wget http://localhost:8080/secret")


def test_allows_public_url_in_command() -> None:
    with patch("opencane.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        assert not contains_internal_url("curl https://example.com/api/data")


def test_no_url_returns_false() -> None:
    assert not contains_internal_url("echo hello && ls -la")

