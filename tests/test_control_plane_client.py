from __future__ import annotations

from typing import Any

import pytest

from nanobot.control_plane import ControlPlaneClient


@pytest.mark.asyncio
async def test_control_plane_runtime_fetch_uses_cache_and_force_refresh() -> None:
    calls: list[tuple[str, dict[str, Any], dict[str, str], float]] = []

    async def _fetch(
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        calls.append((url, dict(params), dict(headers), float(timeout)))
        return {"tts_mode": "server_audio", "no_heartbeat_timeout_s": 90}

    client = ControlPlaneClient(
        enabled=True,
        base_url="https://cp.example.com",
        api_token="tok",
        cache_ttl_seconds=30,
        fetcher=_fetch,
    )
    first = await client.fetch_runtime_config()
    second = await client.fetch_runtime_config()
    third = await client.fetch_runtime_config(force_refresh=True)

    assert first["success"] is True
    assert first["source"] == "remote"
    assert second["source"] == "cache"
    assert third["source"] == "remote"
    assert len(calls) == 2
    assert calls[0][0].endswith("/v1/control/runtime_config")
    assert calls[0][2]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_control_plane_runtime_fetch_falls_back_to_stale_cache() -> None:
    counter = {"n": 0}

    async def _fetch(
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        del url, params, headers, timeout
        counter["n"] += 1
        if counter["n"] == 1:
            return {"tts_mode": "device_text"}
        raise RuntimeError("cp down")

    client = ControlPlaneClient(
        enabled=True,
        base_url="https://cp.example.com",
        cache_ttl_seconds=1,
        fetcher=_fetch,
    )
    first = await client.fetch_runtime_config()
    second = await client.fetch_runtime_config(force_refresh=True)

    assert first["source"] == "remote"
    assert second["success"] is True
    assert second["source"] == "stale_cache"
    assert second["data"]["tts_mode"] == "device_text"
    assert "warning" in second


@pytest.mark.asyncio
async def test_control_plane_runtime_fetch_uses_fallback_when_no_cache() -> None:
    async def _fetch(
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        del url, params, headers, timeout
        raise RuntimeError("cp unreachable")

    client = ControlPlaneClient(
        enabled=True,
        base_url="https://cp.example.com",
        fallback_runtime_config={"tts_mode": "device_text", "no_heartbeat_timeout_s": 80},
        fetcher=_fetch,
    )
    result = await client.fetch_runtime_config()

    assert result["success"] is True
    assert result["source"] == "fallback"
    assert result["data"]["tts_mode"] == "device_text"
    assert "warning" in result


@pytest.mark.asyncio
async def test_control_plane_device_policy_cache_and_failure() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    counter = {"n": 0}

    async def _fetch(
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        del headers, timeout
        calls.append((url, dict(params)))
        counter["n"] += 1
        if counter["n"] == 1:
            return {"allow_tools": ["mcp_maps"]}
        raise RuntimeError("cp policy down")

    client = ControlPlaneClient(
        enabled=True,
        base_url="https://cp.example.com",
        cache_ttl_seconds=30,
        fetcher=_fetch,
    )

    first = await client.fetch_device_policy(device_id="dev-1")
    second = await client.fetch_device_policy(device_id="dev-1")
    third = await client.fetch_device_policy(device_id="dev-1", force_refresh=True)
    missing = await client.fetch_device_policy(device_id="")

    assert first["source"] == "remote"
    assert second["source"] == "cache"
    assert third["source"] == "stale_cache"
    assert third["data"]["allow_tools"] == ["mcp_maps"]
    assert missing["success"] is False
    assert len(calls) == 2
    assert calls[0][0].endswith("/v1/control/device_policy")
    assert calls[0][1]["device_id"] == "dev-1"
