from __future__ import annotations

from typing import Any

import pytest

from nanobot.cli.commands import (
    _apply_control_plane_runtime_overrides,
    _ControlPlaneRuntimeRefresher,
)


class _Runtime:
    def __init__(self) -> None:
        self.tts_mode = "device_text"
        self.no_heartbeat_timeout_s = 60


class _SafetyPolicy:
    def __init__(self) -> None:
        self.low_confidence_threshold = 0.55
        self.max_output_chars = 320


class _ControlPlaneClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def fetch_runtime_config(self, force_refresh: bool = False) -> dict[str, Any]:
        self.calls.append({"force_refresh": bool(force_refresh)})
        if not self.responses:
            return {"success": True, "source": "cache", "data": {}}
        return self.responses.pop(0)


def test_apply_control_plane_runtime_overrides_updates_runtime_and_safety() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    source, warning = _apply_control_plane_runtime_overrides(
        runtime,
        safety,
        {
            "success": True,
            "source": "remote",
            "warning": "cp-warning",
            "data": {
                "tts_mode": "server_audio",
                "no_heartbeat_timeout_s": 95,
                "safety": {
                    "low_confidence_threshold": 0.61,
                    "max_output_chars": 280,
                },
            },
        },
    )
    assert source == "remote"
    assert warning == "cp-warning"
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 95
    assert safety.low_confidence_threshold == 0.61
    assert safety.max_output_chars == 280


@pytest.mark.asyncio
async def test_control_plane_runtime_refresher_initial_and_periodic_refresh() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    now = [0.0]

    def _now() -> float:
        return now[0]

    client = _ControlPlaneClient(
        responses=[
            {
                "success": True,
                "source": "remote",
                "data": {"tts_mode": "device_text", "no_heartbeat_timeout_s": 70},
            },
            {
                "success": True,
                "source": "stale_cache",
                "warning": "cp degraded",
                "data": {"tts_mode": "server_audio", "no_heartbeat_timeout_s": 88},
            },
        ]
    )
    refresher = _ControlPlaneRuntimeRefresher(
        client=client,
        runtime=runtime,
        safety_policy=safety,
        refresh_seconds=5.0,
        now_fn=_now,
    )

    source, warning = await refresher.load_initial()
    assert source == "remote"
    assert warning == ""
    assert runtime.tts_mode == "device_text"
    assert runtime.no_heartbeat_timeout_s == 70
    assert client.calls == [{"force_refresh": False}]

    not_due = await refresher.refresh_if_due()
    assert not_due is None
    assert len(client.calls) == 1

    now[0] = 5.2
    due = await refresher.refresh_if_due()
    assert isinstance(due, dict)
    assert due["source"] == "stale_cache"
    assert due["source_changed"] is True
    assert due["warning_changed"] is True
    assert due["warning"] == "cp degraded"
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 88
    assert client.calls[-1] == {"force_refresh": True}


@pytest.mark.asyncio
async def test_control_plane_runtime_refresher_rejects_non_regressive_version_without_rollback() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    now = [0.0]
    now_ms = [2000]

    def _now() -> float:
        return now[0]

    def _now_ms() -> int:
        return now_ms[0]

    client = _ControlPlaneClient(
        responses=[
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "2", "issued_at_ms": 2000},
                "data": {"tts_mode": "server_audio", "no_heartbeat_timeout_s": 80},
            },
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "1", "issued_at_ms": 1000},
                "data": {"tts_mode": "device_text", "no_heartbeat_timeout_s": 40},
            },
        ]
    )
    refresher = _ControlPlaneRuntimeRefresher(
        client=client,
        runtime=runtime,
        safety_policy=safety,
        refresh_seconds=5.0,
        now_fn=_now,
        now_ms_fn=_now_ms,
    )

    await refresher.load_initial()
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 80

    now[0] = 5.1
    now_ms[0] = 2100
    refreshed = await refresher.refresh_if_due()
    assert isinstance(refreshed, dict)
    assert refreshed["applied"] is False
    assert "non_regressive_version_rejected" in str(refreshed["warning"])
    assert runtime.tts_mode == "server_audio"
    assert runtime.no_heartbeat_timeout_s == 80


@pytest.mark.asyncio
async def test_control_plane_runtime_refresher_allows_rollback_to_lower_version() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    now = [0.0]
    now_ms = [2000]

    def _now() -> float:
        return now[0]

    def _now_ms() -> int:
        return now_ms[0]

    client = _ControlPlaneClient(
        responses=[
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "2", "issued_at_ms": 2000},
                "data": {"tts_mode": "server_audio"},
            },
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "1", "issued_at_ms": 1000, "rollback": True},
                "data": {"tts_mode": "device_text"},
            },
        ]
    )
    refresher = _ControlPlaneRuntimeRefresher(
        client=client,
        runtime=runtime,
        safety_policy=safety,
        refresh_seconds=5.0,
        now_fn=_now,
        now_ms_fn=_now_ms,
    )

    await refresher.load_initial()
    assert runtime.tts_mode == "server_audio"
    now[0] = 5.1
    now_ms[0] = 2100
    refreshed = await refresher.refresh_if_due()
    assert isinstance(refreshed, dict)
    assert refreshed["applied"] is True
    assert runtime.tts_mode == "device_text"


@pytest.mark.asyncio
async def test_control_plane_runtime_refresher_rejects_expired_config() -> None:
    runtime = _Runtime()
    safety = _SafetyPolicy()
    now = [0.0]
    now_ms = [5000]

    def _now() -> float:
        return now[0]

    def _now_ms() -> int:
        return now_ms[0]

    client = _ControlPlaneClient(
        responses=[
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "1", "issued_at_ms": 1000},
                "data": {"tts_mode": "server_audio"},
            },
            {
                "success": True,
                "source": "remote",
                "meta": {"config_version": "2", "issued_at_ms": 1200, "expires_at_ms": 2000},
                "data": {"tts_mode": "device_text"},
            },
        ]
    )
    refresher = _ControlPlaneRuntimeRefresher(
        client=client,
        runtime=runtime,
        safety_policy=safety,
        refresh_seconds=5.0,
        now_fn=_now,
        now_ms_fn=_now_ms,
    )

    await refresher.load_initial()
    assert runtime.tts_mode == "server_audio"
    now[0] = 5.1
    refreshed = await refresher.refresh_if_due()
    assert isinstance(refreshed, dict)
    assert refreshed["applied"] is False
    assert "expired_runtime_config" in str(refreshed["warning"])
    assert runtime.tts_mode == "server_audio"
